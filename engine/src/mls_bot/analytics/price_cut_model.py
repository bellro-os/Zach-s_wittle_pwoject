"""Price-cut probability model — binary classifier.

Given a property at a proposed list price, returns:
    P(this listing will need a price reduction to sell)

Trained on closed sales: target = (final_list_price < original_list_price).
Same feature set as the DOM regressor (price, sqft, beds, etc) but with binary
log-loss instead of quantile regression.

The DOM model says "expect X days." This model adds "Y% chance you'll have to
cut price" — pairing them gives a fuller pricing picture.

Output: probability in [0, 1].
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

from .db import connect
from .dom_model import (
    ALL_FEATURES, CATEGORICAL_FEATURES, NUMERIC_FEATURES,
    _engineer, _load_photo_counts,
    _row_for_subject, ModelBundle as DomBundle, MODEL_DIR as DOM_DIR,
    HIGH_CARDINALITY_LIMIT,
)


CUT_MODEL_DIR = Path("outputs/mls_analytics/price_cut_model")

# Features that LEAK the cut target (final-list and orig-list directly encode it).
# At training time we use original_list_price as the proposed price; we exclude
# list_price (final) and list_to_orig_ratio (=1 when no cut, <1 when cut).
LEAKY_FEATURES = ("list_price", "list_to_orig_ratio")
CUT_NUMERIC_FEATURES = [f for f in NUMERIC_FEATURES if f not in LEAKY_FEATURES]
CUT_ALL_FEATURES = CUT_NUMERIC_FEATURES + CATEGORICAL_FEATURES


def _load_cut_training_frame() -> pd.DataFrame:
    """Same source as DOM model, but only listings with both list_price and
    original_list_price > 0 (to compute the cut target)."""
    con = connect()
    df = con.execute("""
        SELECT
            l.listing_id, l._class,
            UPPER(TRIM(l.city)) AS city,
            l.address, l.subdivision, l.zoning, l.property_subtype,
            l.list_agent, l.list_office,
            TRY_CAST(l.list_price AS DOUBLE) AS list_price,
            TRY_CAST(l.original_list_price AS DOUBLE) AS original_list_price,
            TRY_CAST(l.sold_price AS DOUBLE) AS sold_price,
            TRY_CAST(l.sqft AS DOUBLE) AS sqft,
            TRY_CAST(l.bedrooms AS DOUBLE) AS bedrooms,
            TRY_CAST(l.full_baths AS DOUBLE) AS full_baths,
            TRY_CAST(l.half_baths AS DOUBLE) AS half_baths,
            TRY_CAST(l.acres AS DOUBLE) AS acres,
            TRY_CAST(l.year_built AS DOUBLE) AS year_built,
            TRY_CAST(l.parcel_assessed_total AS DOUBLE) AS parcel_assessed_total,
            TRY_CAST(l.parcel_owner_occupied AS BOOLEAN) AS parcel_owner_occupied,
            TRY_CAST(l.feed_cdom AS DOUBLE) AS cdom,
            TRY_CAST(l.feed_dom AS DOUBLE) AS dom,
            TRY_CAST(l.list_date AS DATE) AS list_date,
            TRY_CAST(l.close_date AS DATE) AS close_date
        FROM listings l
        WHERE l.status_category = 'Closed'
          AND TRY_CAST(l.original_list_price AS DOUBLE) > 0
          AND TRY_CAST(l.list_price AS DOUBLE) > 0
          AND TRY_CAST(l.list_date AS DATE) IS NOT NULL
          AND TRY_CAST(l.close_date AS DATE) IS NOT NULL
    """).fetchdf()
    return df


def train(out_dir: Path | str = CUT_MODEL_DIR,
          *, train_until: str = "2025-09-30") -> dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("loading frame ...")
    df = _load_cut_training_frame()
    print(f"  {len(df):,} closed sales with both prices populated")

    # Target: final list_price < original_list_price
    df["did_cut"] = (df["list_price"] < df["original_list_price"]).astype(int)
    rate = df["did_cut"].mean()
    print(f"  base rate of cuts: {rate*100:.1f}%")

    cutoff = pd.to_datetime(train_until)
    photo_counts = _load_photo_counts()
    # Overwrite list_price with original_list_price BEFORE engineering, so all
    # derived features (price_per_sqft, price_to_assessed_ratio, etc.) reflect
    # the seller's initial asking price, not the post-cut state.
    df = df.copy()
    df["list_price"] = df["original_list_price"]
    train_df_raw = df[df["close_date"] < cutoff].copy()
    val_df_raw = df[df["close_date"] >= cutoff].copy()
    print(f"  train: {len(train_df_raw):,}  val: {len(val_df_raw):,}")

    # Reuse engineering (target encodes agent/office on cdom — that's fine
    # as a useful feature for cut prediction too)
    train_df = _engineer(train_df_raw, photo_counts=photo_counts, is_train=True)
    val_df = _engineer(
        val_df_raw,
        freq_lookup=train_df.attrs.get("freq_lookup", {}),
        agent_means=train_df.attrs.get("agent_means", {}),
        office_means=train_df.attrs.get("office_means", {}),
        photo_counts=photo_counts,
        is_train=False,
    )
    val_df.attrs["agent_global_mean"] = train_df.attrs["agent_global_mean"]
    val_df.attrs["office_global_mean"] = train_df.attrs["office_global_mean"]

    cat_indices = [i for i, c in enumerate(CUT_ALL_FEATURES) if c in CATEGORICAL_FEATURES]

    def prep(d):
        X = d.reindex(columns=CUT_ALL_FEATURES).copy()
        for c in CATEGORICAL_FEATURES:
            X[c] = X[c].astype("category")
        return X

    X_train = prep(train_df)
    y_train = train_df["did_cut"]
    X_val = prep(val_df)
    y_val = val_df["did_cut"]

    print("  fitting binary classifier ...")
    clf = HistGradientBoostingClassifier(
        loss="log_loss",
        max_iter=400,
        max_depth=8,
        learning_rate=0.05,
        min_samples_leaf=20,
        categorical_features=cat_indices,
        random_state=42,
    )
    clf.fit(X_train, y_train)

    # Validation
    from sklearn.metrics import roc_auc_score, brier_score_loss
    p_val = clf.predict_proba(X_val)[:, 1]
    auc = roc_auc_score(y_val, p_val)
    brier = brier_score_loss(y_val, p_val)
    # Calibration: in 5 buckets of predicted probability, what's the actual rate?
    bins = np.linspace(0, 1, 6)
    cal: list[dict] = []
    for i in range(5):
        mask = (p_val >= bins[i]) & (p_val < bins[i+1] if i < 4 else p_val <= bins[i+1])
        if mask.sum() < 5: continue
        cal.append({
            "predicted_range": f"{bins[i]*100:.0f}-{bins[i+1]*100:.0f}%",
            "n": int(mask.sum()),
            "predicted_avg": round(float(p_val[mask].mean()), 3),
            "actual_rate": round(float(y_val[mask].mean()), 3),
        })

    metrics = {
        "auc": round(float(auc), 4),
        "brier": round(float(brier), 4),
        "base_rate_train": round(float(y_train.mean()), 4),
        "base_rate_val": round(float(y_val.mean()), 4),
        "train_n": int(len(train_df)),
        "val_n": int(len(val_df)),
        "calibration": cal,
    }

    joblib.dump(clf, out_dir / "cut_clf.joblib")
    joblib.dump({
        "feature_order": CUT_ALL_FEATURES,
        "categorical_indices": cat_indices,
        "freq_lookup": train_df.attrs.get("freq_lookup", {}),
        "agent_means": train_df.attrs.get("agent_means", {}),
        "office_means": train_df.attrs.get("office_means", {}),
        "agent_global_mean": train_df.attrs.get("agent_global_mean", 21.0),
        "office_global_mean": train_df.attrs.get("office_global_mean", 21.0),
        "training_metrics": metrics,
        "trained_at": datetime.now().isoformat(timespec="seconds"),
    }, out_dir / "cut_meta.joblib")

    # Markdown report
    lines = [
        "# Price-cut classifier — training report",
        "",
        f"- trained_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- training rows: {metrics['train_n']:,}",
        f"- val rows: {metrics['val_n']:,}",
        f"- base rate of cuts (train): {metrics['base_rate_train']*100:.1f}%",
        f"- AUC: {metrics['auc']}",
        f"- Brier score: {metrics['brier']}",
        "",
        "## Calibration (predicted vs actual cut rate)",
        "",
        "| Predicted range | n | Predicted avg | Actual rate |",
        "|---|---:|---:|---:|",
    ]
    for c in cal:
        lines.append(f"| {c['predicted_range']} | {c['n']} | {c['predicted_avg']} | {c['actual_rate']} |")
    (out_dir / "training_report.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"\n=== cut classifier ===")
    print(f"  AUC: {metrics['auc']}  Brier: {metrics['brier']}  base rate: {metrics['base_rate_train']*100:.1f}%")
    return metrics


def predict_cut_probability(subject: dict, proposed_price: float) -> float | None:
    """Probability this listing will need a price cut. None if model not trained."""
    if not (CUT_MODEL_DIR / "cut_clf.joblib").exists():
        return None
    clf = joblib.load(CUT_MODEL_DIR / "cut_clf.joblib")
    meta = joblib.load(CUT_MODEL_DIR / "cut_meta.joblib")
    # Build a lightweight DomBundle-shaped object so _row_for_subject works
    class _B:
        freq_lookup = meta["freq_lookup"]
        agent_means = meta["agent_means"]
        office_means = meta["office_means"]
        agent_global_mean = float(meta["agent_global_mean"])
        office_global_mean = float(meta["office_global_mean"])
    X_full = _row_for_subject(subject, proposed_price, freq_lookup=_B.freq_lookup, bundle=_B())  # type: ignore
    # Drop leaky features that the cut classifier was trained without
    X = X_full.reindex(columns=CUT_ALL_FEATURES)
    p = float(clf.predict_proba(X)[0, 1])
    return round(p, 3)

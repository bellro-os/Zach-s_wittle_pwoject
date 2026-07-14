"""Predictive AVM — automated valuation model for any NRV parcel.

Trains a HistGradientBoostingRegressor on MLS Closed sales (2023+) using
parcel + listing features. Predicts current market value for any property
given features alone — useful for:
  - Sellers who haven't transacted recently (paired with seller-score)
  - Buyers asking "what's this worth?"
  - Tax-appeal evidence
  - Past-client equity-update emails

Output: outputs/mls_analytics/avm_model/regressor.joblib + meta.

Note: simpler than the DOM model (single regressor, no quantile loss).
Re-uses the DOM model's feature pipeline (target encoding, freq lookup, etc).
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_absolute_percentage_error

from .db import connect
from .dom_model import (
    NUMERIC_FEATURES, CATEGORICAL_FEATURES,
    _engineer, _load_photo_counts, _row_for_subject, ModelBundle,
)


AVM_DIR = Path("outputs/mls_analytics/avm_model")

# Drop list_price from features (it IS the target, near-tautology).
# Keep original_list_price out for the same reason.
AVM_LEAKY = ("list_price", "original_list_price", "list_to_orig_ratio", "price_per_sqft", "price_to_assessed_ratio")
AVM_NUMERIC = [f for f in NUMERIC_FEATURES if f not in AVM_LEAKY]
AVM_FEATURES = AVM_NUMERIC + CATEGORICAL_FEATURES


def _load_training_frame() -> pd.DataFrame:
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
          AND TRY_CAST(l.sold_price AS DOUBLE) > 30000
          AND TRY_CAST(l.close_date AS DATE) IS NOT NULL
          AND TRY_CAST(l.list_date AS DATE) IS NOT NULL
    """).fetchdf()
    return df


def train(out_dir: Path | str = AVM_DIR,
          *, train_until: str = "2025-09-30",
          price_max: float = 3_500_000) -> dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("loading frame ...")
    df = _load_training_frame()
    df = df[(df["sold_price"] > 30_000) & (df["sold_price"] < price_max)].copy()
    print(f"  {len(df):,} closed sales (price 30k-{price_max/1e6:.1f}M)")

    cutoff = pd.to_datetime(train_until)
    photo_counts = _load_photo_counts()
    train_df_raw = df[df["close_date"] < cutoff].copy()
    val_df_raw = df[df["close_date"] >= cutoff].copy()
    print(f"  train: {len(train_df_raw):,}  val: {len(val_df_raw):,}")
    if len(train_df_raw) < 500:
        raise RuntimeError(f"only {len(train_df_raw)} training rows — not enough")

    # Engineering reuses the DOM-model pipeline (target encoding, freq lookup)
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

    cat_indices = [i for i, c in enumerate(AVM_FEATURES) if c in CATEGORICAL_FEATURES]

    def prep(d):
        X = d.reindex(columns=AVM_FEATURES).copy()
        for c in CATEGORICAL_FEATURES:
            X[c] = X[c].astype("category")
        return X

    X_train = prep(train_df)
    y_train = train_df["sold_price"].astype("float")
    X_val = prep(val_df)
    y_val = val_df["sold_price"].astype("float")

    # Use log-target to handle wide price range better
    y_train_log = np.log1p(y_train)

    print("  fitting AVM regressor (log target)...")
    reg = HistGradientBoostingRegressor(
        loss="squared_error",
        max_iter=500,
        max_depth=8,
        learning_rate=0.04,
        min_samples_leaf=20,
        categorical_features=cat_indices,
        random_state=42,
    )
    reg.fit(X_train, y_train_log)

    # Validation metrics (back-transform from log)
    pred_log = reg.predict(X_val)
    pred = np.expm1(pred_log)
    mae = float(mean_absolute_error(y_val, pred))
    mape = float(mean_absolute_percentage_error(y_val, pred))
    median_ape = float(np.median(np.abs(pred - y_val) / y_val))

    metrics = {
        "mae": round(mae, 0),
        "mape": round(mape * 100, 2),
        "median_abs_pct_error": round(median_ape * 100, 2),
        "train_n": int(len(train_df)),
        "val_n": int(len(val_df)),
    }

    joblib.dump(reg, out_dir / "regressor.joblib")
    joblib.dump({
        "feature_order": AVM_FEATURES,
        "categorical_indices": cat_indices,
        "freq_lookup": train_df.attrs.get("freq_lookup", {}),
        "agent_means": train_df.attrs.get("agent_means", {}),
        "office_means": train_df.attrs.get("office_means", {}),
        "agent_global_mean": train_df.attrs.get("agent_global_mean", 21.0),
        "office_global_mean": train_df.attrs.get("office_global_mean", 21.0),
        "training_metrics": metrics,
        "trained_at": datetime.now().isoformat(timespec="seconds"),
    }, out_dir / "meta.joblib")

    lines = [
        "# AVM (automated valuation model) — training report",
        "",
        f"- trained_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- training rows: {metrics['train_n']:,}",
        f"- val rows: {metrics['val_n']:,}",
        f"- MAE: ${int(metrics['mae']):,}",
        f"- MAPE: {metrics['mape']}%",
        f"- median |pct error|: {metrics['median_abs_pct_error']}%",
        "",
        "## Features",
        "",
        "**numeric:** " + ", ".join(AVM_NUMERIC),
        "",
        "**categorical:** " + ", ".join(CATEGORICAL_FEATURES),
        "",
        "Trained on a log-transformed target. Drops `list_price`, `original_list_price`,",
        "`list_to_orig_ratio`, `price_per_sqft`, `price_to_assessed_ratio` (leak the target).",
    ]
    (out_dir / "training_report.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"\n=== AVM trained ===")
    print(f"  MAE: ${int(metrics['mae']):,}")
    print(f"  MAPE: {metrics['mape']}%")
    print(f"  median |pct error|: {metrics['median_abs_pct_error']}%")
    return metrics


# Module-level cache so repeated predicts (e.g. the CMA ensemble across many
# subjects, or the backtest loop) don't re-read the joblib artifacts from disk
# on every call — loading the regressor is ~7s, predicting is sub-100ms.
_MODEL_CACHE: dict[str, Any] = {}


def _load_model():
    """Load (and cache) the trained regressor + meta bundle, or None if absent."""
    if not (AVM_DIR / "regressor.joblib").exists():
        return None
    if "reg" not in _MODEL_CACHE:
        reg = joblib.load(AVM_DIR / "regressor.joblib")
        meta = joblib.load(AVM_DIR / "meta.joblib")

        class _B:
            freq_lookup = meta["freq_lookup"]
            agent_means = meta["agent_means"]
            office_means = meta["office_means"]
            agent_global_mean = float(meta["agent_global_mean"])
            office_global_mean = float(meta["office_global_mean"])

        _MODEL_CACHE["reg"] = reg
        _MODEL_CACHE["bundle"] = _B()
    return _MODEL_CACHE["reg"], _MODEL_CACHE["bundle"]


def predict(subject: dict) -> float | None:
    """Predict current market value for a property given subject features."""
    loaded = _load_model()
    if loaded is None:
        return None
    reg, bundle = loaded

    # Generate the row using DOM-model's row builder (it includes all numeric
    # + categorical features), then drop the leaky cols
    proposed_price = float(subject.get("list_price") or subject.get("parcel_assessed_total") or 250_000)
    X_full = _row_for_subject(subject, proposed_price, freq_lookup=bundle.freq_lookup, bundle=bundle)  # type: ignore
    X = X_full.reindex(columns=AVM_FEATURES)
    pred_log = reg.predict(X)[0]
    return float(np.expm1(pred_log))


def predict_for_parcel(parcel_id: str) -> dict | None:
    """Look up parcel's most-recent listing record (if any) for features, then
    predict. If parcel has never been MLS-listed, falls back to parcel JSONL data."""
    con = connect()
    r = con.execute(f"""
        SELECT
            address, UPPER(TRIM(city)) AS city, _class,
            TRY_CAST(bedrooms AS INT) AS bedrooms,
            TRY_CAST(full_baths AS INT) AS full_baths,
            TRY_CAST(half_baths AS INT) AS half_baths,
            TRY_CAST(sqft AS DOUBLE) AS sqft,
            TRY_CAST(acres AS DOUBLE) AS acres,
            TRY_CAST(year_built AS INT) AS year_built,
            subdivision, zoning, property_subtype,
            TRY_CAST(parcel_assessed_total AS DOUBLE) AS parcel_assessed_total,
            TRY_CAST(parcel_owner_occupied AS BOOLEAN) AS parcel_owner_occupied,
            list_agent, list_office
        FROM listings
        WHERE parcel_id = '{parcel_id.replace(chr(39), chr(39)*2)}'
        ORDER BY list_date DESC NULLS LAST LIMIT 1
    """).fetchone()
    if not r:
        return None
    cols = ["address","city","_class","bedrooms","full_baths","half_baths","sqft",
            "acres","year_built","subdivision","zoning","property_subtype",
            "parcel_assessed_total","parcel_owner_occupied","list_agent","list_office"]
    subject = dict(zip(cols, r))
    val = predict(subject)
    return {
        "parcel_id": parcel_id,
        "subject": subject,
        "predicted_value": round(val, 0) if val else None,
    }

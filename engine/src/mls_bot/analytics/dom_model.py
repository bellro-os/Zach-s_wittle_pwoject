"""Predictive DOM model — quantile regression for days-on-market.

Three HistGradientBoostingRegressor instances trained at q=0.25, 0.50, 0.75
give a prediction interval per property: p25 (fast case), p50 (median),
p75 (slow case). HistGBR handles missing values + categoricals natively.

Public API:
    train(out_dir=..., year_min_train=2023, year_min_validate=...) -> training summary
    load() -> ModelBundle
    predict_dom(subject_dict, proposed_price, bundle=None) -> {"p25":..., "p50":..., "p75":...}
    recommend_price_for_target_dom(subject_dict, target_dom, bundle=None) -> {...}

Training data: data/mls/listings_plus_deeds.jsonl, status_category='Closed'
with valid sold_price + close_date + cdom.

Output artifacts: outputs/mls_analytics/dom_model/
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error

from .db import connect


MODEL_DIR = Path("outputs/mls_analytics/dom_model")
QUANTILES = (0.25, 0.50, 0.75)

NUMERIC_FEATURES = [
    "list_price", "original_list_price", "sqft", "bedrooms",
    "full_baths", "half_baths", "acres", "year_built",
    "parcel_assessed_total",
    # engineered
    "price_per_sqft", "age_at_list", "list_month",
    "price_to_assessed_ratio",
    "list_to_orig_ratio",       # 1.0 = no cuts; <1 = price was reduced
    "n_photos",                  # marketing investment proxy
    "agent_dom_signature",       # target-encoded mean DOM for the listing agent
    "office_dom_signature",      # target-encoded mean DOM for the listing office
]

CATEGORICAL_FEATURES = [
    "city", "_class", "property_subtype",
    "subdivision", "zoning",
    "parcel_owner_occupied",
]

ALL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES


@dataclass
class ModelBundle:
    models: dict
    feature_order: list[str]
    categorical_indices: list[int]
    cohort_medians: dict
    freq_lookup: dict
    agent_means: dict
    office_means: dict
    agent_global_mean: float
    office_global_mean: float


def _load_training_frame() -> pd.DataFrame:
    con = connect()
    # Register media + listings_history if available
    media_path = Path("data/mls/listings_media.jsonl")
    if media_path.exists():
        con.execute(f"""
            CREATE OR REPLACE VIEW _media AS
            SELECT listing_id, n_photos
            FROM read_json_auto('{media_path.as_posix()}', format='newline_delimited',
                                 union_by_name=true, sample_size=-1)
        """)
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
          AND TRY_CAST(l.sold_price AS DOUBLE) > 0
          AND TRY_CAST(l.close_date AS DATE) IS NOT NULL
          AND TRY_CAST(l.list_date AS DATE) IS NOT NULL
          AND TRY_CAST(l.feed_cdom AS DOUBLE) IS NOT NULL
    """).fetchdf()
    return df


HIGH_CARDINALITY_LIMIT = 250  # HistGBR caps at 255; leave headroom


def _load_photo_counts() -> dict:
    """Return {listing_id: n_photos} from data/mls/listings_media.jsonl, or {}."""
    p = Path("data/mls/listings_media.jsonl")
    if not p.exists():
        return {}
    out: dict = {}
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
                lid = r.get("listing_id")
                if lid:
                    out[str(lid)] = r.get("n_photos") or 0
            except Exception:
                continue
    return out


def _engineer(
    df: pd.DataFrame,
    freq_lookup: dict | None = None,
    *,
    agent_means: dict | None = None,
    office_means: dict | None = None,
    photo_counts: dict | None = None,
    is_train: bool = True,
) -> pd.DataFrame:
    """Engineer features. When training, target-encode agent/office DOM means
    on the input frame (avoids leakage by passing only training data here).
    When predicting, pass the precomputed maps."""
    df = df.copy()
    df["price_per_sqft"] = np.where(
        (df["sqft"].fillna(0) > 0) & (df["list_price"].fillna(0) > 0),
        df["list_price"] / df["sqft"], np.nan
    )
    df["age_at_list"] = np.where(
        df["year_built"].fillna(0) > 1700,
        df["list_date"].dt.year - df["year_built"], np.nan
    )
    df["list_month"] = df["list_date"].dt.month.astype("float")
    df["price_to_assessed_ratio"] = np.where(
        df["parcel_assessed_total"].fillna(0) > 0,
        df["list_price"] / df["parcel_assessed_total"], np.nan
    )
    df["list_to_orig_ratio"] = np.where(
        df["original_list_price"].fillna(0) > 0,
        df["list_price"] / df["original_list_price"], np.nan
    )

    # Photo count
    if photo_counts is None:
        photo_counts = _load_photo_counts()
    df["n_photos"] = df["listing_id"].astype(str).map(photo_counts).fillna(0).astype("float")

    # Target-encoded agent / office DOM signatures
    if is_train and "cdom" in df.columns:
        # Compute on this frame (only on training rows when caller passes train_df)
        agent_means = df.dropna(subset=["list_agent"]).groupby(
            df["list_agent"].astype(str)
        )["cdom"].mean().to_dict()
        office_means = df.dropna(subset=["list_office"]).groupby(
            df["list_office"].astype(str)
        )["cdom"].mean().to_dict()
        # Global fallback for unseen agents/offices at predict time
        global_mean_agent = float(df["cdom"].mean())
        df.attrs["agent_means"] = agent_means
        df.attrs["office_means"] = office_means
        df.attrs["agent_global_mean"] = global_mean_agent
        df.attrs["office_global_mean"] = global_mean_agent
    if agent_means is None:
        agent_means = {}
    if office_means is None:
        office_means = {}
    g_agent = df.attrs.get("agent_global_mean") or 21.0
    g_office = df.attrs.get("office_global_mean") or 21.0
    df["agent_dom_signature"] = df["list_agent"].astype(str).map(agent_means).fillna(g_agent)
    df["office_dom_signature"] = df["list_office"].astype(str).map(office_means).fillna(g_office)

    # Coerce categoricals to strings (HistGBR needs str/categorical)
    for c in CATEGORICAL_FEATURES:
        df[c] = df[c].astype(str).where(df[c].notna(), other=None)
    # Cap high-cardinality categoricals: keep top N, replace rest with "OTHER"
    if freq_lookup is None:
        freq_lookup = {}
        for c in ("subdivision", "city"):
            counts = df[c].value_counts()
            keepers = set(counts.head(HIGH_CARDINALITY_LIMIT).index)
            freq_lookup[c] = keepers
    for c, keepers in freq_lookup.items():
        df[c] = df[c].where(df[c].isin(keepers), other="OTHER")
    df.attrs["freq_lookup"] = freq_lookup
    return df


def _prepare_X(df: pd.DataFrame) -> pd.DataFrame:
    X = df.reindex(columns=ALL_FEATURES).copy()
    # HistGBR wants categoricals as pandas Categorical or strings; convert
    for c in CATEGORICAL_FEATURES:
        X[c] = X[c].astype("category")
    return X


def train(
    out_dir: Path | str = MODEL_DIR,
    *,
    train_until: str = "2025-09-30",
    cdom_max: int = 180,
    cdom_min: int = 0,
) -> dict[str, Any]:
    """Train q25/q50/q75 quantile models. Returns summary dict, also writes
    artifacts + training_report.md to out_dir."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"loading training frame ...")
    df_raw = _load_training_frame()
    print(f"  {len(df_raw):,} closed sales total")

    # Outlier filter first (before any feature engineering)
    df_raw = df_raw[(df_raw["cdom"] >= cdom_min) & (df_raw["cdom"] <= cdom_max)].copy()
    print(f"  {len(df_raw):,} after outlier filter (cdom in [{cdom_min}, {cdom_max}])")

    cutoff = pd.to_datetime(train_until)
    photo_counts = _load_photo_counts()
    print(f"  photo counts loaded: {len(photo_counts):,} listings")

    # Engineer training frame first (computes agent/office means from training only — no leakage)
    train_df_raw = df_raw[df_raw["close_date"] < cutoff].copy()
    val_df_raw = df_raw[df_raw["close_date"] >= cutoff].copy()
    print(f"  train: {len(train_df_raw):,} (close_date < {cutoff.date()})")
    print(f"  val:   {len(val_df_raw):,} (close_date >= {cutoff.date()})")
    if len(train_df_raw) < 200:
        raise RuntimeError(f"only {len(train_df_raw)} training rows — refusing to train")

    train_df = _engineer(train_df_raw, photo_counts=photo_counts, is_train=True)
    agent_means = train_df.attrs.get("agent_means", {})
    office_means = train_df.attrs.get("office_means", {})
    g_agent = train_df.attrs.get("agent_global_mean", 21.0)
    g_office = train_df.attrs.get("office_global_mean", 21.0)
    freq_lookup = train_df.attrs.get("freq_lookup", {})

    val_df = _engineer(val_df_raw, freq_lookup=freq_lookup,
                        agent_means=agent_means, office_means=office_means,
                        photo_counts=photo_counts, is_train=False)
    val_df.attrs["agent_global_mean"] = g_agent
    val_df.attrs["office_global_mean"] = g_office

    X_train = _prepare_X(train_df)
    y_train = train_df["cdom"].astype("float")
    X_val = _prepare_X(val_df)
    y_val = val_df["cdom"].astype("float") if len(val_df) else None

    cat_indices = [i for i, c in enumerate(ALL_FEATURES) if c in CATEGORICAL_FEATURES]

    models: dict = {}
    for q in QUANTILES:
        print(f"  training q={q} ...")
        t0 = time.time()
        m = HistGradientBoostingRegressor(
            loss="quantile",
            quantile=q,
            max_iter=400,
            max_depth=8,
            learning_rate=0.05,
            min_samples_leaf=20,
            categorical_features=cat_indices,
            random_state=42,
        )
        m.fit(X_train, y_train)
        models[q] = m
        print(f"    fit in {time.time()-t0:.1f}s")

    # Validation metrics
    metrics: dict[str, Any] = {}
    if y_val is not None and len(y_val) > 0:
        preds: dict[float, np.ndarray] = {}
        for q in QUANTILES:
            preds[q] = models[q].predict(X_val)
        mae50 = float(mean_absolute_error(y_val, preds[0.50]))
        in_band = ((y_val >= preds[0.25]) & (y_val <= preds[0.75])).mean()
        def pinball(y, yhat, q):
            d = y - yhat
            return float(np.maximum(q * d, (q - 1) * d).mean())
        metrics["mae_p50"] = round(mae50, 2)
        metrics["p25_p75_coverage"] = round(float(in_band), 3)
        metrics["pinball_q25"] = round(pinball(y_val, preds[0.25], 0.25), 2)
        metrics["pinball_q50"] = round(pinball(y_val, preds[0.50], 0.50), 2)
        metrics["pinball_q75"] = round(pinball(y_val, preds[0.75], 0.75), 2)
        metrics["val_n"] = int(len(y_val))
        # Per-class MAE
        per_class: dict[str, dict] = {}
        for cls in val_df["_class"].unique():
            mask = (val_df["_class"] == cls).values
            if mask.sum() < 5:
                continue
            y_cls = y_val[mask]
            p50_cls = preds[0.50][mask]
            p25_cls = preds[0.25][mask]
            p75_cls = preds[0.75][mask]
            per_class[cls] = {
                "n": int(mask.sum()),
                "mae_p50": round(float(mean_absolute_error(y_cls, p50_cls)), 1),
                "coverage": round(float(((y_cls >= p25_cls) & (y_cls <= p75_cls)).mean()), 3),
                "median_actual_cdom": round(float(y_cls.median()), 1),
            }
        metrics["per_class"] = per_class
    metrics["train_n"] = int(len(train_df))

    # Cohort medians used as fallback when categorical is unseen at predict time
    cohort_medians = {
        "city_dom": train_df.groupby("city")["cdom"].median().to_dict(),
        "class_dom": train_df.groupby("_class")["cdom"].median().to_dict(),
        "global_dom": float(train_df["cdom"].median()),
    }

    bundle = {
        "models": models,
        "feature_order": ALL_FEATURES,
        "categorical_indices": cat_indices,
        "cohort_medians": cohort_medians,
        "freq_lookup": freq_lookup,
        "agent_means": agent_means,
        "office_means": office_means,
        "agent_global_mean": g_agent,
        "office_global_mean": g_office,
        "training_metrics": metrics,
        "trained_at": datetime.now().isoformat(timespec="seconds"),
    }

    for q in QUANTILES:
        joblib.dump(models[q], out_dir / f"q{int(q*100):02d}.joblib")
    joblib.dump(
        {k: v for k, v in bundle.items() if k != "models"},
        out_dir / "bundle_meta.joblib",
    )

    # Markdown report
    report = ["# DOM model training report", ""]
    report.append(f"- trained_at: {bundle['trained_at']}")
    report.append(f"- training rows: {metrics['train_n']:,}")
    if "val_n" in metrics:
        report.append(f"- validation rows: {metrics['val_n']:,}")
        report.append(f"- median-prediction MAE: {metrics['mae_p50']} days")
        report.append(f"- p25-p75 interval coverage: {metrics['p25_p75_coverage']*100:.1f}% (target ~50%)")
        report.append(f"- pinball loss: q25={metrics['pinball_q25']}, q50={metrics['pinball_q50']}, q75={metrics['pinball_q75']}")
    report.append("")
    report.append(f"## features ({len(ALL_FEATURES)})")
    report.append("")
    report.append("**numeric:** " + ", ".join(NUMERIC_FEATURES))
    report.append("")
    report.append("**categorical:** " + ", ".join(CATEGORICAL_FEATURES))
    (out_dir / "training_report.md").write_text("\n".join(report), encoding="utf-8")

    print(f"\n=== training summary ===")
    for k, v in metrics.items():
        print(f"  {k}: {v}")
    return metrics


def load(model_dir: Path | str = MODEL_DIR) -> ModelBundle:
    model_dir = Path(model_dir)
    meta = joblib.load(model_dir / "bundle_meta.joblib")
    models = {q: joblib.load(model_dir / f"q{int(q*100):02d}.joblib") for q in QUANTILES}
    return ModelBundle(
        models=models,
        feature_order=meta["feature_order"],
        categorical_indices=meta["categorical_indices"],
        cohort_medians=meta["cohort_medians"],
        freq_lookup=meta.get("freq_lookup", {}),
        agent_means=meta.get("agent_means", {}),
        office_means=meta.get("office_means", {}),
        agent_global_mean=float(meta.get("agent_global_mean", 21.0)),
        office_global_mean=float(meta.get("office_global_mean", 21.0)),
    )


def _row_for_subject(subject: dict, proposed_price: float,
                     freq_lookup: dict | None = None,
                     bundle: ModelBundle | None = None) -> pd.DataFrame:
    """Build a 1-row feature frame from a subject dict + proposed price."""
    today = date.today()
    yb = subject.get("year_built")
    sqft = subject.get("sqft")
    assessed = subject.get("parcel_assessed_total") or subject.get("assessed_total")
    row = {
        "list_price": float(proposed_price),
        "original_list_price": float(proposed_price),
        "sqft": float(sqft) if sqft else np.nan,
        "bedrooms": float(subject.get("bedrooms") or np.nan),
        "full_baths": float(subject.get("full_baths") or np.nan),
        "half_baths": float(subject.get("half_baths") or np.nan),
        "acres": float(subject.get("acres") or np.nan),
        "year_built": float(yb) if yb else np.nan,
        "parcel_assessed_total": float(assessed) if assessed else np.nan,
        "price_per_sqft": (float(proposed_price) / float(sqft)) if (sqft and float(sqft) > 0) else np.nan,
        "age_at_list": (today.year - float(yb)) if yb else np.nan,
        "list_month": float(today.month),
        "price_to_assessed_ratio": (float(proposed_price) / float(assessed)) if (assessed and float(assessed) > 0) else np.nan,
        "city": (subject.get("city") or "").upper().strip() or None,
        "_class": subject.get("_class") or "RE_1",
        "property_subtype": subject.get("property_subtype"),
        "subdivision": (subject.get("subdivision") or "").upper().strip() or None,
        "zoning": subject.get("zoning"),
        "parcel_owner_occupied": str(subject.get("parcel_owner_occupied")) if subject.get("parcel_owner_occupied") is not None else None,
    }
    # New features
    orig = subject.get("original_list_price")
    row["list_to_orig_ratio"] = (float(proposed_price) / float(orig)) if (orig and float(orig) > 0) else 1.0
    row["n_photos"] = float(subject.get("n_photos") or 0)
    if bundle:
        agent_id = str(subject.get("list_agent") or "")
        office_id = str(subject.get("list_office") or "")
        row["agent_dom_signature"] = float(bundle.agent_means.get(agent_id, bundle.agent_global_mean))
        row["office_dom_signature"] = float(bundle.office_means.get(office_id, bundle.office_global_mean))
    else:
        row["agent_dom_signature"] = 21.0
        row["office_dom_signature"] = 21.0
    df = pd.DataFrame([row])
    if freq_lookup:
        for c, keepers in freq_lookup.items():
            if c in df.columns:
                df[c] = df[c].where(df[c].isin(keepers), other="OTHER")
    for c in CATEGORICAL_FEATURES:
        df[c] = df[c].astype("category")
    return df.reindex(columns=ALL_FEATURES)


def predict_dom(subject: dict, proposed_price: float,
                bundle: ModelBundle | None = None) -> dict[str, Any]:
    """Predict p25 / p50 / p75 DOM for a property at a proposed price."""
    if bundle is None:
        bundle = load()
    X = _row_for_subject(subject, proposed_price, freq_lookup=bundle.freq_lookup, bundle=bundle)
    out = {}
    for q in QUANTILES:
        out[f"p{int(q*100):02d}"] = float(bundle.models[q].predict(X)[0])
    out["p25"] = round(out["p25"], 1)
    out["p50"] = round(out["p50"], 1)
    out["p75"] = round(out["p75"], 1)
    return out


def recommend_price_for_target_dom(
    subject: dict,
    target_dom: float,
    *,
    cohort_median_price: float | None = None,
    bundle: ModelBundle | None = None,
    grid_step: int = 5_000,
    sweep_pct: float = 0.25,
) -> dict[str, Any]:
    """Sweep prices around the cohort median and return the band whose
    predicted p50 DOM is at or below `target_dom`.

    If no cohort_median_price is given, falls back to subject.list_price
    or assessed_total."""
    if bundle is None:
        bundle = load()
    anchor = (cohort_median_price
              or subject.get("list_price")
              or subject.get("parcel_assessed_total")
              or 250_000)
    anchor = float(anchor)
    lo = max(int(anchor * (1 - sweep_pct)), 25_000)
    hi = int(anchor * (1 + sweep_pct))
    grid = list(range(lo, hi + grid_step, grid_step))

    rows = []
    for p in grid:
        pred = predict_dom(subject, float(p), bundle=bundle)
        rows.append({"price": p, **pred})
    df = pd.DataFrame(rows)
    hits = df[df["p50"] <= target_dom]
    out: dict[str, Any] = {
        "target_dom": target_dom,
        "anchor_price": int(anchor),
        "grid_price_min": lo,
        "grid_price_max": hi,
    }
    if hits.empty:
        # Even the cheapest price didn't hit; report the lowest predicted DOM
        best = df.loc[df["p50"].idxmin()]
        out["feasible"] = False
        out["closest_price"] = int(best["price"])
        out["closest_p50"] = float(best["p50"])
        out["note"] = f"target {target_dom}d not reachable in grid; cheapest price hits p50≈{best['p50']:.0f}d"
    else:
        # Highest price still hitting target = "sweet spot" (don't underprice)
        sweet = hits["price"].max()
        out["feasible"] = True
        out["min_price"] = int(hits["price"].min())
        out["max_price"] = int(sweet)
        out["sweet_spot"] = int(sweet)
        out["predicted_p50_at_sweet_spot"] = round(float(hits[hits["price"] == sweet]["p50"].iloc[0]), 1)
    return out

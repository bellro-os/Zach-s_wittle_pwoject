"""Per-neighborhood (subdivision) performance analytics for a single city.

For each subdivision with enough activity, computes closed-sale velocity,
volume, days-on-market, list-to-sale ratio, recent trend, geographic
centroid, the dominant brokerage and its market share, and the top 3
listing-agent IDs (names require a future agent-directory join — IDs only
for now).

Output: outputs/mls_analytics/neighborhoods_<city_slug>.csv

Auto-runs in mls-daily.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

from .db import connect


OUT_DIR = Path("outputs/mls_analytics")
MIN_CLOSES_12MO = 2   # filter out subdivisions with no real activity
MIN_CLOSES_LIFETIME = 8  # but keep historically-meaningful ones even if recently quiet


def _safe_slug(city: str) -> str:
    return city.strip().lower().replace(" ", "_").replace(",", "")


def build_neighborhood_stats(city: str = "Blacksburg") -> int:
    """Build the per-subdivision CSV for one city. Returns row count."""
    con = connect()
    cu = city.upper()

    # 1) Headline per-subdivision performance + centroid (12mo and 6mo windows).
    perf_sql = f"""
    WITH bb AS (
      SELECT
        subdivision,
        TRY_CAST(close_date AS DATE) AS cd,
        TRY_CAST(sold_price AS DOUBLE) AS sp,
        TRY_CAST(original_list_price AS DOUBLE) AS olp,
        TRY_CAST(feed_dom AS INT) AS dom,
        TRY_CAST(latitude AS DOUBLE) AS lat,
        TRY_CAST(longitude AS DOUBLE) AS lng
      FROM listings
      WHERE UPPER(city) = '{cu}'
        AND status_category = 'Closed'
        AND subdivision IS NOT NULL
        AND TRIM(subdivision) NOT IN ('','-','None','OTHER','UNKNOWN','none','other','Other')
    )
    SELECT
      subdivision,
      COUNT(*) FILTER (WHERE cd >= CURRENT_DATE - INTERVAL 12 MONTH) AS closes_12mo,
      COUNT(*) FILTER (WHERE cd >= CURRENT_DATE - INTERVAL  6 MONTH) AS closes_6mo,
      COUNT(*) FILTER (WHERE cd <  CURRENT_DATE - INTERVAL  6 MONTH
                       AND   cd >= CURRENT_DATE - INTERVAL 12 MONTH) AS closes_prior_6mo,
      COUNT(*) AS closes_all_time,
      SUM(sp)  FILTER (WHERE cd >= CURRENT_DATE - INTERVAL 12 MONTH) AS volume_12mo,
      AVG(dom) FILTER (WHERE cd >= CURRENT_DATE - INTERVAL 12 MONTH) AS avg_dom,
      MEDIAN(sp) FILTER (WHERE cd >= CURRENT_DATE - INTERVAL 12 MONTH) AS median_price,
      AVG(sp * 100.0 / NULLIF(olp, 0))
        FILTER (WHERE cd >= CURRENT_DATE - INTERVAL 12 MONTH) AS avg_list_to_sale_pct,
      -- Bound the centroid to a sane Blacksburg-area lat/lng range so
      -- mis-geocoded listings (occasional Roanoke-area lng on a Blacksburg
      -- subdivision row) don't yank the average off-map.
      AVG(lat) FILTER (WHERE lat BETWEEN 37.18 AND 37.30) AS centroid_lat,
      AVG(lng) FILTER (WHERE lng BETWEEN -80.55 AND -80.30) AS centroid_lng
    FROM bb
    GROUP BY subdivision
    HAVING closes_12mo >= {MIN_CLOSES_12MO} OR closes_all_time >= {MIN_CLOSES_LIFETIME}
    ORDER BY closes_12mo DESC, closes_all_time DESC
    """
    perf_rows = con.execute(perf_sql).fetchall()
    perf_cols = [d[0] for d in con.description]
    perf: dict[str, dict] = {}
    for r in perf_rows:
        rec = dict(zip(perf_cols, r))
        perf[rec["subdivision"]] = rec

    # 2) Dominant brokerage per subdivision (last 12mo) + market share.
    office_sql = f"""
    WITH ranked AS (
      SELECT
        subdivision,
        list_office_name AS office,
        COUNT(*) AS n,
        SUM(COUNT(*)) OVER (PARTITION BY subdivision) AS total,
        ROW_NUMBER() OVER (PARTITION BY subdivision ORDER BY COUNT(*) DESC, list_office_name) AS r
      FROM listings
      WHERE UPPER(city) = '{cu}'
        AND status_category = 'Closed'
        AND TRY_CAST(close_date AS DATE) >= CURRENT_DATE - INTERVAL 12 MONTH
        AND subdivision IS NOT NULL
        AND list_office_name IS NOT NULL AND TRIM(list_office_name) <> ''
      GROUP BY 1, 2
    )
    SELECT subdivision, office, n, total, ROUND(100.0 * n / total, 1) AS share_pct
    FROM ranked WHERE r = 1
    """
    for r in con.execute(office_sql).fetchall():
        subd, office, n, total, share = r
        if subd in perf:
            perf[subd]["top_office"] = office
            perf[subd]["top_office_closes"] = int(n)
            perf[subd]["top_office_share_pct"] = float(share)

    # 3) Top 3 listing-agent IDs per subdivision (last 12mo). Names require
    #    a future join against the agent directory; surface IDs for now.
    agent_sql = f"""
    SELECT subdivision, list_agent AS agent_id, COUNT(*) AS n
    FROM listings
    WHERE UPPER(city) = '{cu}'
      AND status_category = 'Closed'
      AND TRY_CAST(close_date AS DATE) >= CURRENT_DATE - INTERVAL 12 MONTH
      AND subdivision IS NOT NULL
      AND list_agent IS NOT NULL AND TRIM(list_agent) <> ''
    GROUP BY 1, 2
    """
    by_subd: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for subd, aid, n in con.execute(agent_sql).fetchall():
        by_subd[subd].append((aid, int(n)))
    for subd, items in by_subd.items():
        if subd not in perf:
            continue
        items.sort(key=lambda x: (-x[1], x[0]))
        top3 = items[:3]
        perf[subd]["top_agents_json"] = json.dumps(
            [{"id": aid, "n": n} for aid, n in top3]
        )
        if top3:
            perf[subd]["top_agent_id"] = top3[0][0]
            perf[subd]["top_agent_closes"] = top3[0][1]

    # 4) Velocity trend — last-6mo vs prior-6mo closes (>1.0 = accelerating).
    for subd, rec in perf.items():
        prior = rec.get("closes_prior_6mo") or 0
        recent = rec.get("closes_6mo") or 0
        if prior > 0:
            rec["velocity_trend"] = round(recent / prior, 2)
        elif recent > 0:
            rec["velocity_trend"] = 99.0  # "infinitely up" sentinel for prev=0 case
        else:
            rec["velocity_trend"] = 0.0

    # 5) Hot flag — top quartile by 12mo closes.
    counts = sorted([r["closes_12mo"] or 0 for r in perf.values()])
    p75 = counts[int(len(counts) * 0.75)] if counts else 0
    for rec in perf.values():
        rec["is_hot"] = (rec["closes_12mo"] or 0) >= max(p75, 3)

    # Emit
    out_path = OUT_DIR / f"neighborhoods_{_safe_slug(city)}.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cols = [
        "subdivision", "closes_12mo", "closes_6mo", "closes_prior_6mo",
        "velocity_trend", "is_hot", "closes_all_time",
        "volume_12mo", "avg_dom", "median_price", "avg_list_to_sale_pct",
        "centroid_lat", "centroid_lng",
        "top_office", "top_office_closes", "top_office_share_pct",
        "top_agent_id", "top_agent_closes", "top_agents_json",
    ]
    def fmt(v):
        if v is None: return ""
        if isinstance(v, bool): return "true" if v else "false"
        if isinstance(v, float): return f"{v:.2f}" if abs(v) >= 1 else f"{v:.3f}"
        return v
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for subd, rec in sorted(
            perf.items(),
            key=lambda kv: (-(kv[1].get("closes_12mo") or 0), kv[0]),
        ):
            w.writerow([fmt(rec.get(c)) for c in cols])
    return len(perf)

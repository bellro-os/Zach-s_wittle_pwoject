"""Saved-search alerts — store criteria as YAML, run daily, alert on diffs.

Each named search produces:
  outputs/mls_analytics/saved_search_alerts/<name>_current.csv  — current matches
  outputs/mls_analytics/saved_search_alerts/<name>_new.csv      — only new since last run
  outputs/mls_analytics/saved_search_alerts/<name>_dropped.csv  — gone since last run

State (last-run match list) is persisted in
data/saved_search_state/<name>.txt as a list of listing_ids.
"""

from __future__ import annotations

import csv
from pathlib import Path

from .alerts import watch_listings


CONFIG_PATH = Path("config/saved_searches.yaml")
ALERTS_DIR = Path("outputs/mls_analytics/saved_search_alerts")
STATE_DIR = Path("data/saved_search_state")


def _load_searches() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        import yaml
        return (yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}).get("searches") or {}
    except Exception:
        return {}


def _read_listing_ids(csv_path: Path) -> set[str]:
    if not csv_path.exists():
        return set()
    out: set[str] = set()
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            lid = (row.get("listing_id") or "").strip()
            if lid:
                out.add(lid)
    return out


def _write_subset(src_csv: Path, ids: set[str], dst_csv: Path) -> int:
    if not src_csv.exists() or not ids:
        dst_csv.parent.mkdir(parents=True, exist_ok=True)
        dst_csv.write_text("listing_id\n", encoding="utf-8-sig")
        return 0
    rows: list[dict] = []
    with src_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if (row.get("listing_id") or "").strip() in ids:
                rows.append(row)
    if not rows:
        dst_csv.write_text("listing_id\n", encoding="utf-8-sig")
        return 0
    fields = list(rows[0].keys())
    dst_csv.parent.mkdir(parents=True, exist_ok=True)
    with dst_csv.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return len(rows)


def run_all_saved_searches() -> dict:
    searches = _load_searches()
    if not searches:
        return {"status": "no_searches_configured"}
    ALERTS_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    summary: dict[str, dict] = {}
    for name, cfg in searches.items():
        cur_csv = ALERTS_DIR / f"{name}_current.csv"
        new_csv = ALERTS_DIR / f"{name}_new.csv"
        dropped_csv = ALERTS_DIR / f"{name}_dropped.csv"
        state_path = STATE_DIR / f"{name}.txt"

        # Build the watch query from yaml
        n = watch_listings(
            cities=cfg.get("cities"),
            classes=cfg.get("classes") or ["RE_1"],
            statuses=cfg.get("statuses") or ["Active", "Pending"],
            min_price=cfg.get("min_price"),
            max_price=cfg.get("max_price"),
            min_beds=cfg.get("min_beds"),
            max_beds=cfg.get("max_beds"),
            min_full_baths=cfg.get("min_full_baths"),
            min_sqft=cfg.get("min_sqft"),
            max_sqft=cfg.get("max_sqft"),
            min_acres=cfg.get("min_acres"),
            max_acres=cfg.get("max_acres"),
            zoning_like=cfg.get("zoning_like"),
            subdivision_like=cfg.get("subdivision_like"),
            school_districts=cfg.get("school_districts"),
            center_lat=cfg.get("center_lat"),
            center_lng=cfg.get("center_lng"),
            radius_mi=cfg.get("radius_mi"),
            listed_within_days=cfg.get("listed_within_days"),
            out_csv=cur_csv,
        )
        cur_ids = _read_listing_ids(cur_csv)
        prev_ids: set[str] = set()
        if state_path.exists():
            prev_ids = {ln.strip() for ln in state_path.read_text(encoding="utf-8").splitlines() if ln.strip()}

        new_ids = cur_ids - prev_ids
        dropped_ids = prev_ids - cur_ids

        n_new = _write_subset(cur_csv, new_ids, new_csv)
        # For dropped, we don't have row data anymore; just write the IDs
        dropped_csv.parent.mkdir(parents=True, exist_ok=True)
        with dropped_csv.open("w", encoding="utf-8-sig") as f:
            f.write("listing_id\n")
            for lid in sorted(dropped_ids):
                f.write(f"{lid}\n")

        # Update state
        state_path.write_text("\n".join(sorted(cur_ids)), encoding="utf-8")

        summary[name] = {
            "description": cfg.get("description") or "",
            "current_n": n, "new_n": n_new, "dropped_n": len(dropped_ids),
        }

    return summary


def render_alerts_index(out_path: Path = ALERTS_DIR / "index.html") -> Path:
    """Render a single index.html linking all saved-search outputs."""
    searches = _load_searches()
    rows = []
    for name, cfg in searches.items():
        desc = cfg.get("description") or ""
        cur = (ALERTS_DIR / f"{name}_current.csv")
        new = (ALERTS_DIR / f"{name}_new.csv")
        n_cur = sum(1 for _ in cur.open()) - 1 if cur.exists() else 0
        n_new = sum(1 for _ in new.open()) - 1 if new.exists() else 0
        rows.append(f"""
<tr><td><strong>{name}</strong><br><small>{desc}</small></td>
    <td><a href="{name}_current.csv">{n_cur} current</a></td>
    <td><a href="{name}_new.csv">{n_new} new</a></td>
    <td><a href="{name}_dropped.csv">dropped</a></td></tr>""")
    html = f"""<!doctype html>
<html><head><meta charset=utf-8><title>Saved-search alerts</title>
<style>body{{font-family:-apple-system,Segoe UI,Helvetica,sans-serif;max-width:900px;margin:30px auto;padding:0 20px}}
table{{border-collapse:collapse;width:100%;font-size:13px;margin-top:14px}}
th,td{{border-bottom:1px solid #eee;padding:8px;text-align:left}}
th{{background:#f0f4f8;font-size:11px;text-transform:uppercase;letter-spacing:.5px}}
small{{color:#777}}
</style></head><body>
<h1>Saved-search alerts</h1>
<p>Edit <code>config/saved_searches.yaml</code> to add or modify searches. Re-run <code>python tasks.py mls-saved-searches</code> to refresh.</p>
<table><tr><th>Search</th><th>Current matches</th><th>New since last run</th><th>Dropped</th></tr>
{"".join(rows)}
</table></body></html>"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path

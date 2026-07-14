"""Render an interactive Folium map of DC candidates + supporting infra.

Layers (toggleable):
  - Candidate parcels: top N by score, color-graded
  - Substations: ≥115 kV, sized by voltage class
  - Transmission lines: color by voltage class
  - Wastewater treatment outfalls
  - Power plants (with MW capacity in popup)
  - Opportunity zone polygons (light fill)

Output: outputs/dc_candidates_map.html

Open the file in a browser. Each candidate has a popup with score, acres,
slope, distance to substation, owner, and Google-Maps directions link.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import folium
from folium.plugins import MarkerCluster


def _color_for_score(score: float) -> str:
    if score >= 75: return "darkgreen"
    if score >= 65: return "green"
    if score >= 55: return "orange"
    if score >= 45: return "lightred"
    return "gray"


def _voltage_color(kv: int | None) -> str:
    if kv is None: return "#888888"
    if kv >= 500: return "#cc0000"
    if kv >= 230: return "#cc6600"
    if kv >= 115: return "#cc9900"
    return "#999999"


def _voltage_weight(kv: int | None) -> float:
    if kv is None: return 1.5
    if kv >= 500: return 4
    if kv >= 230: return 3
    if kv >= 115: return 2
    return 1.5


def _candidate_popup(row: dict) -> str:
    score = float(row.get("score_dc") or 0)
    acres = row.get("acres") or "?"
    site = row.get("site") or "(no addr)"
    owner = row.get("owner") or ""
    county = row.get("county") or ""
    sub_mi = row.get("miles_to_sub_min_volt") or "?"
    sub_kv = row.get("min_volt_at_nearest_sub_kv") or "?"
    slope = row.get("slope_mean_pct") or "?"
    pct5 = row.get("pct_under_5pct_slope") or "?"
    wwtp_mi = row.get("miles_to_wwtp") or "?"
    line_mi = row.get("miles_to_transmission_line") or "?"
    plant_mi = row.get("miles_to_power_plant") or "?"
    res_mi = row.get("miles_to_nearest_residential") or "?"
    in_oz = row.get("in_opportunity_zone") or ""
    in_flood = row.get("in_floodplain") or ""
    parcel_id = row.get("parcel_id") or ""
    lat = row.get("lat")
    lng = row.get("lng")
    gmaps_url = f"https://www.google.com/maps/search/?api=1&query={lat},{lng}" if lat and lng else "#"
    zoning = row.get("zoning") or ""
    assessed = row.get("assessed_total") or ""
    return f"""
    <b>Score: {score:.0f}</b> &middot; {acres} ac &middot; {county}<br>
    <b>{site}</b><br>
    Owner: {owner}<br>
    Parcel: {parcel_id}{'  &middot;  Zoning: ' + str(zoning) if zoning else ''}<br>
    {('Assessed: $' + str(int(float(assessed))) + '<br>') if assessed else ''}
    Sub: {sub_mi} mi @ {sub_kv} kV<br>
    Slope: {slope}% (under 5%: {pct5}%)<br>
    WWTP: {wwtp_mi} mi &middot; Line: {line_mi} mi &middot; Plant: {plant_mi} mi<br>
    Nearest residential: {res_mi} mi<br>
    Opp Zone: {'Yes' if in_oz == 'Y' else 'No'} &middot; Floodplain: {'YES' if in_flood == 'Y' else 'No'}<br>
    <a href='{gmaps_url}' target='_blank'>Open in Google Maps &raquo;</a>
    """.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates-csv", default="outputs/dc_candidates_statewide.csv")
    ap.add_argument("--top-n", type=int, default=200,
                    help="how many top candidates to plot (default 200)")
    ap.add_argument("--out", default="outputs/dc_candidates_map.html")
    args = ap.parse_args()

    root = Path(__file__).parent.parent

    # 1. Load candidates (by score desc, top-N)
    cand_path = root / args.candidates_csv
    if not cand_path.exists():
        print(f"error: {cand_path} not found", file=sys.stderr)
        return 2
    with cand_path.open("r", encoding="utf-8-sig") as f:
        cand_rows = list(csv.DictReader(f))
    cand_rows.sort(key=lambda r: -float(r.get("score_dc") or 0))
    cand_rows = cand_rows[:args.top_n]
    print(f"  candidates: {len(cand_rows)} (top by score)")

    # Center the map on the centroid of plotted candidates
    valid = [(float(r["lat"]), float(r["lng"])) for r in cand_rows
             if r.get("lat") and r.get("lng")]
    if not valid:
        print("no valid candidate coords; cannot render map")
        return 1
    lat0 = sum(p[0] for p in valid) / len(valid)
    lng0 = sum(p[1] for p in valid) / len(valid)

    m = folium.Map(location=[lat0, lng0], zoom_start=8, tiles="cartodbpositron")
    folium.TileLayer("OpenStreetMap").add_to(m)

    # 2. Candidate parcels — clustered for performance
    cand_layer = folium.FeatureGroup(name=f"DC Candidates (top {len(cand_rows)})", show=True)
    cluster = MarkerCluster().add_to(cand_layer)
    for r in cand_rows:
        try:
            lat = float(r["lat"]); lng = float(r["lng"])
        except (KeyError, TypeError, ValueError):
            continue
        score = float(r.get("score_dc") or 0)
        folium.CircleMarker(
            location=[lat, lng],
            radius=8,
            color="black", weight=1, opacity=0.9,
            fill=True, fill_color=_color_for_score(score), fill_opacity=0.85,
            popup=folium.Popup(_candidate_popup(r), max_width=380),
            tooltip=f"#{cand_rows.index(r)+1} score {score:.0f}  {(r.get('site') or '')[:30]}",
        ).add_to(cluster)
    cand_layer.add_to(m)

    # 3. Substations (≥115 kV) with capacity proxy badges (Tier 13)
    subs_path = root / "data" / "va_substations.jsonl"
    if subs_path.exists():
        # Lazy-load PJM queue lookup — empty dict if file is missing
        try:
            import sys as _sys
            _sys.path.insert(0, str(root / "src"))
            from mls_bot.analytics.dc_capacity import load_pjm_queue_by_sub, canon_sub_name
            pjm_lookup = load_pjm_queue_by_sub()
        except Exception:
            pjm_lookup = {}
            canon_sub_name = lambda x: (x or "").upper()
        sub_layer = folium.FeatureGroup(name="Substations (≥115 kV)", show=True)
        n_subs = 0
        with subs_path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip(): continue
                s = json.loads(line)
                kv = s.get("max_volt_kv")
                try:
                    kv_int = int(kv) if kv is not None else None
                except (TypeError, ValueError):
                    kv_int = None
                if kv_int is None or kv_int < 115 or kv_int == -999999:
                    continue
                lat = s.get("lat"); lng = s.get("lng")
                if lat is None or lng is None:
                    continue
                # Capacity proxy + queue lookup
                lines = s.get("lines") or 0
                try:
                    lines = int(lines) if lines != -999999 else 0
                except (TypeError, ValueError):
                    lines = 0
                cap_proxy = kv_int * (max(lines, 1) ** 0.5)
                # Tier badge by capacity
                if cap_proxy >= 1000:   tier = "HYPER"
                elif cap_proxy >= 500:  tier = "HIGH"
                elif cap_proxy >= 250:  tier = "MED"
                else:                   tier = "LOW"
                sub_canon = canon_sub_name(s.get("name") or "")
                queue_mw = (pjm_lookup.get(sub_canon) or {}).get("queue_mw", 0.0)
                queue_str = f"<br><b>PJM queue:</b> {queue_mw:,.0f} MW" if queue_mw else ""
                folium.CircleMarker(
                    location=[lat, lng],
                    radius=4 + (kv_int // 100) + (1 if tier == "HYPER" else 0),
                    color=_voltage_color(kv_int), weight=1,
                    fill=True, fill_color=_voltage_color(kv_int), fill_opacity=0.7,
                    popup=(f"<b>{s.get('name')}</b><br>{kv_int} kV · {lines} lines"
                           f"<br><b>cap_proxy: {cap_proxy:.0f}</b> ({tier})"
                           f"{queue_str}<br>{s.get('city')}"),
                    tooltip=f"{s.get('name')}  {tier} cap={cap_proxy:.0f}",
                ).add_to(sub_layer)
                n_subs += 1
        sub_layer.add_to(m)
        print(f"  substations plotted: {n_subs}")

    # 4. Transmission lines
    lines_path = root / "data" / "va_transmission_lines.jsonl"
    if lines_path.exists():
        line_layer = folium.FeatureGroup(name="Transmission Lines", show=True)
        n_lines = 0
        with lines_path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip(): continue
                ln = json.loads(line)
                kv_raw = ln.get("voltage")
                try:
                    kv_int = int(kv_raw) if kv_raw is not None else None
                except (TypeError, ValueError):
                    kv_int = None
                for path_pts in ln.get("paths") or []:
                    coords = [(p[1], p[0]) for p in path_pts
                              if isinstance(p, (list, tuple)) and len(p) >= 2]
                    if len(coords) < 2:
                        continue
                    folium.PolyLine(
                        coords,
                        color=_voltage_color(kv_int),
                        weight=_voltage_weight(kv_int),
                        opacity=0.7,
                        tooltip=f"{kv_int} kV  {ln.get('owner') or ''}",
                    ).add_to(line_layer)
                    n_lines += 1
        line_layer.add_to(m)
        print(f"  transmission segments plotted: {n_lines}")

    # 5. Wastewater treatment plants
    wwtp_path = root / "data" / "va_wastewater_treatment.jsonl"
    if wwtp_path.exists():
        ww_layer = folium.FeatureGroup(name="Wastewater Treatment", show=False)
        n_w = 0
        with wwtp_path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip(): continue
                w = json.loads(line)
                lat = w.get("lat"); lng = w.get("lng")
                if lat is None or lng is None: continue
                folium.CircleMarker(
                    location=[lat, lng],
                    radius=3, color="#0066cc", weight=1,
                    fill=True, fill_color="#0066cc", fill_opacity=0.6,
                    tooltip=w.get("facility_name") or "",
                ).add_to(ww_layer)
                n_w += 1
        ww_layer.add_to(m)
        print(f"  wwtp plotted: {n_w}")

    # 6. Power plants
    plants_path = root / "data" / "va_power_plants.jsonl"
    if plants_path.exists():
        pp_layer = folium.FeatureGroup(name="Power Plants", show=False)
        n_p = 0
        with plants_path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip(): continue
                p = json.loads(line)
                lat = p.get("lat"); lng = p.get("lng")
                if lat is None or lng is None: continue
                mw = p.get("total_mw")
                folium.CircleMarker(
                    location=[lat, lng],
                    radius=4 + (min(float(mw), 2000) / 250 if mw else 0),
                    color="#990099", weight=1,
                    fill=True, fill_color="#cc99cc", fill_opacity=0.7,
                    tooltip=f"{p.get('plant_name')}  {mw} MW",
                    popup=f"<b>{p.get('plant_name')}</b><br>{mw} MW &middot; {p.get('primary_source')}<br>{p.get('city')}, VA",
                ).add_to(pp_layer)
                n_p += 1
        pp_layer.add_to(m)
        print(f"  power plants plotted: {n_p}")

    # 7. Opportunity zones (transparent fill)
    oz_path = root / "data" / "va_opportunity_zones.jsonl"
    if oz_path.exists():
        oz_layer = folium.FeatureGroup(name="Opportunity Zones", show=False)
        n_oz = 0
        with oz_path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip(): continue
                z = json.loads(line)
                rings = z.get("rings") or []
                if not rings: continue
                # Folium expects [[lat, lng], ...]
                coords = []
                for ring in rings:
                    coords.append([(p[1], p[0]) for p in ring
                                   if isinstance(p, (list, tuple)) and len(p) >= 2])
                if not coords: continue
                folium.Polygon(
                    locations=coords[0],
                    color="#3366cc", weight=1, opacity=0.5,
                    fill=True, fill_color="#3366cc", fill_opacity=0.12,
                    tooltip=f"OZ {z.get('tract')} ({z.get('county')})",
                ).add_to(oz_layer)
                n_oz += 1
        oz_layer.add_to(m)
        print(f"  opp zones plotted: {n_oz}")

    folium.LayerControl(collapsed=False).add_to(m)

    out_path = root / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(out_path))
    print(f"  saved: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

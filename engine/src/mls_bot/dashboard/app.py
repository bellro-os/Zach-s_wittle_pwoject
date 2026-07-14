"""Flask entrypoint for the local realtor dashboard.

Run:
    PYTHONPATH=src python -m mls_bot.dashboard.app
"""

from __future__ import annotations

import os
import webbrowser
from pathlib import Path

from flask import (Flask, render_template, request, redirect, url_for,
                    abort, send_from_directory)

from . import data_layer as dl
from .call_scripts import (
    ALL_LEAD_TYPES, opener_for, label_for, chip_class_for,
)


BASE_DIR = Path(__file__).resolve().parent
app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
)

# Expose lead-type helpers to all Jinja templates
app.jinja_env.globals["opener_for"] = opener_for
app.jinja_env.globals["lead_label"] = label_for
app.jinja_env.globals["lead_chip_class"] = chip_class_for


# ---------- Filter parsing (shared by home + fragment endpoint) -----------

def _parse_filters() -> dict:
    """Pull all filter params from the query string into a single dict."""
    return {
        "mode": request.args.get("mode", "call"),
        "min_score": int(request.args.get("min_score", 50)),
        "counties": [c for c in request.args.getlist("counties") if c],
        "owner_types": [t for t in request.args.getlist("owner_types") if t],
        "signals": [s for s in request.args.getlist("signals") if s],
        "lead_types": [t for t in request.args.getlist("lead_types") if t],
        "suppress_days": int(request.args.get("suppress_days", 60)),
        "sort_by": request.args.get("sort_by", "score"),
        "max_rows": int(request.args.get("max_rows", 50)),
        "skip_flippers": request.args.get("skip_flippers", "1") != "0",
        "subdivisions": [s for s in request.args.getlist("subdivisions") if s],
    }


def _build_queue(f: dict) -> list[dict]:
    """Dispatch to the right queue builder based on mode."""
    if f["mode"] == "knock":
        return dl.doorknock_queue(
            min_score=f["min_score"],
            counties=f["counties"] or None,
            subdivisions=f["subdivisions"] or None,
            signal_must_have=f["signals"] or None,
            lead_types=f["lead_types"] or None,
            suppress_within_days=f["suppress_days"],
            max_rows=f["max_rows"],
        )
    return dl.call_queue(
        min_score=f["min_score"],
        counties=f["counties"] or None,
        owner_types=f["owner_types"] or None,
        signal_must_have=f["signals"] or None,
        lead_types=f["lead_types"] or None,
        suppress_within_days=f["suppress_days"],
        sort_by=f["sort_by"],
        max_rows=f["max_rows"],
        skip_flippers=f["skip_flippers"],
    )


# ---------- Home: today's call queue --------------------------------------

@app.route("/")
def home():
    filters = _parse_filters()
    queue = _build_queue(filters)
    groups = dl.subdivision_groups(queue) if filters["mode"] == "knock" else None
    return render_template(
        "home.html",
        queue=queue,
        groups=groups,
        stats=dl.quick_stats(),
        hot=dl.hot_prospects(within_days=30),
        followups=dl.followups_due(within_days=3),
        counties=dl.known_counties(),
        subdivisions=dl.known_subdivisions(limit=80),
        lead_type_counts=dl.lead_type_counts(min_score=filters["min_score"]),
        all_lead_types=ALL_LEAD_TYPES,
        filters=filters,
        is_fragment=False,
    )


@app.route("/_fragments/queue")
def queue_fragment():
    """HTMX-target endpoint: returns just the queue table HTML."""
    filters = _parse_filters()
    queue = _build_queue(filters)
    groups = dl.subdivision_groups(queue) if filters["mode"] == "knock" else None
    return render_template(
        "_queue_fragment.html",
        queue=queue,
        groups=groups,
        filters=filters,
    )


@app.route("/_fragments/row_detail/<parcel_id>")
def row_detail_fragment(parcel_id: str):
    """HTMX-target endpoint: returns the score-breakdown expansion panel."""
    county = (request.args.get("county") or "").strip()
    row = dl.seller_score_row(parcel_id, county=county)
    if not row:
        return ('<tr class="row-detail"><td colspan="9" '
                'class="px-4 py-3 text-sm text-slate-500">'
                'Detail not found for this parcel.</td></tr>'), 200
    breakdown = dl.score_breakdown(row)
    return render_template(
        "_row_detail.html",
        row=row,
        breakdown=breakdown,
        parcel_id=parcel_id,
    )


# ---------- Call-log action endpoint --------------------------------------

def _outcome_confirmation_fragment(parcel_id: str, outcome: str,
                                    followup_days: int | None,
                                    channel: str) -> str:
    """Tiny inline-replace row indicating a logged outcome (HTMX)."""
    days = followup_days if followup_days is not None else \
        dl.OUTCOME_FOLLOWUP_DAYS.get(outcome, 30)
    icon = "🚪" if channel == "knock" else "📞"
    fu = f' · follow up in {days}d' if days < 36000 else ' · suppressed'
    return (
        f'<tr id="row-{parcel_id}" class="bg-green-50">'
        f'<td colspan="9" class="px-4 py-2 text-sm text-green-800 italic">'
        f'{icon} logged · {outcome.replace("_", " ")}{fu}'
        f'</td></tr>'
    )


@app.post("/calls/log")
def log_call():
    parcel_id = request.form.get("parcel_id", "").strip()
    county = request.form.get("county", "").strip()
    owner = request.form.get("owner", "").strip()
    site_addr = request.form.get("site_addr", "").strip()
    outcome = request.form.get("outcome", "").strip()
    notes = request.form.get("notes", "").strip()
    followup_days = request.form.get("followup_days", "").strip()

    if not parcel_id or not outcome:
        abort(400, "parcel_id and outcome are required")

    dl.log_call(
        parcel_id=parcel_id, county=county, owner=owner,
        site_addr=site_addr, outcome=outcome, notes=notes,
        custom_followup_days=int(followup_days) if followup_days else None,
    )

    if request.headers.get("HX-Request"):
        return _outcome_confirmation_fragment(
            parcel_id, outcome,
            int(followup_days) if followup_days else None,
            channel="call",
        )
    return redirect(url_for("home"))


@app.post("/doorknocks/log")
def log_doorknock():
    parcel_id = request.form.get("parcel_id", "").strip()
    county = request.form.get("county", "").strip()
    owner = request.form.get("owner", "").strip()
    site_addr = request.form.get("site_addr", "").strip()
    outcome = request.form.get("outcome", "").strip()
    notes = request.form.get("notes", "").strip()
    if not parcel_id or not outcome:
        abort(400, "parcel_id and outcome are required")
    dl.log_doorknock(
        parcel_id=parcel_id, county=county, owner=owner,
        site_addr=site_addr, outcome=outcome, notes=notes,
    )
    if request.headers.get("HX-Request"):
        return _outcome_confirmation_fragment(
            parcel_id, outcome, None, channel="knock",
        )
    return redirect(url_for("home", mode="knock"))


@app.post("/calls/log/bulk")
def log_call_bulk():
    """Apply one outcome to a list of parcel_ids in one shot."""
    outcome = request.form.get("outcome", "").strip()
    parcel_ids = [p for p in request.form.getlist("parcel_ids") if p]
    counties = request.form.getlist("counties")
    owners = request.form.getlist("owners")
    addrs = request.form.getlist("addrs")
    if not outcome or not parcel_ids:
        abort(400, "outcome and parcel_ids are required")
    for i, pid in enumerate(parcel_ids):
        dl.log_call(
            parcel_id=pid,
            county=counties[i] if i < len(counties) else "",
            owner=owners[i] if i < len(owners) else "",
            site_addr=addrs[i] if i < len(addrs) else "",
            outcome=outcome,
        )
    return redirect(request.referrer or url_for("home"))


@app.post("/doorknocks/log/bulk")
def log_doorknock_bulk():
    outcome = request.form.get("outcome", "").strip()
    parcel_ids = [p for p in request.form.getlist("parcel_ids") if p]
    counties = request.form.getlist("counties")
    owners = request.form.getlist("owners")
    addrs = request.form.getlist("addrs")
    if not outcome or not parcel_ids:
        abort(400, "outcome and parcel_ids are required")
    for i, pid in enumerate(parcel_ids):
        dl.log_doorknock(
            parcel_id=pid,
            county=counties[i] if i < len(counties) else "",
            owner=owners[i] if i < len(owners) else "",
            site_addr=addrs[i] if i < len(addrs) else "",
            outcome=outcome,
        )
    return redirect(request.referrer or url_for("home", mode="knock"))


# ---------- Clients (Phase 2) ---------------------------------------------

@app.route("/clients")
def clients_index():
    clients = dl.read_clients()
    clients.sort(key=lambda r: r.get("created", ""), reverse=True)
    return render_template("clients.html", clients=clients)


@app.post("/clients/add")
def clients_add():
    cid = dl.add_client(
        name=request.form.get("name", ""),
        phone=request.form.get("phone", ""),
        email=request.form.get("email", ""),
        source=request.form.get("source", ""),
        anniversary=request.form.get("anniversary", ""),
        notes=request.form.get("notes", ""),
    )
    return redirect(url_for("clients_index"))


# ---------- Deals + Pipeline (Phase 3) ------------------------------------

@app.route("/pipeline")
def pipeline():
    deals = dl.latest_deals()
    clients_by_id = {c["client_id"]: c for c in dl.read_clients()}

    stages = ["lead", "showing", "offer", "contract", "closing", "closed"]
    by_stage = {s: [] for s in stages}
    for d in deals:
        stage = (d.get("stage") or "lead").lower()
        d["_client_name"] = clients_by_id.get(d.get("client_id", ""), {}).get("name", "—")
        by_stage.setdefault(stage, []).append(d)

    stage_totals = {}
    for s, items in by_stage.items():
        total = sum(_safe_float(d.get("list_price")) for d in items)
        stage_totals[s] = {"count": len(items), "dollars": total}

    return render_template(
        "pipeline.html",
        stages=stages,
        by_stage=by_stage,
        totals=stage_totals,
    )


@app.post("/deals/add")
def deals_add():
    dl.add_deal(
        client_id=request.form.get("client_id", ""),
        stage=request.form.get("stage", "lead"),
        side=request.form.get("side", "sell"),
        property=request.form.get("property", ""),
        list_price=_safe_float(request.form.get("list_price")),
        expected_close=request.form.get("expected_close", ""),
        est_commission_pct=_safe_float(request.form.get("est_commission_pct", "3.0")),
        notes=request.form.get("notes", ""),
    )
    return redirect(url_for("pipeline"))


@app.post("/deals/<deal_id>/stage")
def deals_stage_change(deal_id: str):
    new_stage = request.form.get("stage", "")
    dl.update_deal_stage(deal_id, new_stage, notes=request.form.get("notes", ""))
    return redirect(url_for("pipeline"))


# ---------- Search (Phase 4) ----------------------------------------------

@app.route("/search")
def search():
    q = (request.args.get("q") or "").strip()
    results = {"properties": [], "clients": [], "owners": []}

    if q and len(q) >= 2:
        # Client name match
        for c in dl.read_clients():
            if q.lower() in (c.get("name") or "").lower():
                results["clients"].append(c)

        # MLS / parcel search via DuckDB
        try:
            from mls_bot.analytics.db import connect
            con = connect()
            q_safe = q.replace("'", "''").upper()
            rows = con.execute(f"""
                SELECT listing_id, address, city, status_category, _class,
                       TRY_CAST(list_price AS DOUBLE) AS list_price,
                       TRY_CAST(sold_price AS DOUBLE) AS sold_price,
                       TRY_CAST(close_date AS DATE) AS close_date,
                       parcel_id, county,
                       parcel_owner1, TRY_CAST(parcel_assessed_total AS DOUBLE) AS assessed
                FROM listings
                WHERE UPPER(address) LIKE '%{q_safe}%'
                   OR UPPER(parcel_owner1) LIKE '%{q_safe}%'
                ORDER BY status_category = 'Active' DESC, close_date DESC NULLS LAST
                LIMIT 40
            """).fetchdf().to_dict(orient="records")
            results["properties"] = rows
        except Exception as e:
            results["error"] = str(e)

    return render_template("search.html", q=q, results=results)


# ---------- Property deep page --------------------------------------------

@app.route("/property/<parcel_id>")
def property_page(parcel_id):
    from mls_bot.analytics.db import connect
    con = connect()
    pid_safe = parcel_id.replace("'", "''")
    rows = con.execute(f"""
        SELECT * FROM listings
        WHERE parcel_id = '{pid_safe}'
        ORDER BY status_category = 'Active' DESC, list_date DESC
        LIMIT 10
    """).fetchdf().to_dict(orient="records")
    if not rows:
        abort(404)
    # Call history for this parcel
    calls = [c for c in dl.read_calls() if c.get("parcel_id") == parcel_id]
    calls.sort(key=lambda c: c.get("timestamp", ""), reverse=True)
    return render_template(
        "property.html",
        listings=rows,
        latest=rows[0],
        parcel_id=parcel_id,
        calls=calls,
    )


# ---------- Walking route (Part D) ----------------------------------------

@app.route("/route/<path:subdivision>")
def walking_route(subdivision: str):
    """Printable door-knock route for a subdivision (or special token 'queue'
    for the current full queue)."""
    min_score = int(request.args.get("min_score", 50))
    suppress_days = int(request.args.get("suppress_days", 60))
    counties = [c for c in request.args.getlist("counties") if c]
    max_rows = int(request.args.get("max_rows", 200))
    if subdivision == "_queue":
        rows = dl.doorknock_queue(
            min_score=min_score,
            counties=counties or None,
            suppress_within_days=suppress_days,
            max_rows=max_rows,
        )
        title = f"Door-knock route · top {len(rows)} prospects"
    else:
        rows = dl.doorknock_queue(
            min_score=min_score,
            counties=counties or None,
            subdivisions=[subdivision],
            suppress_within_days=suppress_days,
            max_rows=max_rows,
        )
        title = f"Door-knock route · {subdivision}"
    from mls_bot.analytics.geo_cluster import order_walking_route
    ordered = order_walking_route(rows)
    return render_template(
        "route.html",
        rows=ordered,
        title=title,
        subdivision=subdivision,
    )


# ---------- Helpers --------------------------------------------------------

def _safe_float(v) -> float:
    try:
        return float(v) if v not in ("", None) else 0.0
    except (TypeError, ValueError):
        return 0.0


# Template filters
@app.template_filter("money")
def _money(v) -> str:
    try:
        f = float(v)
        return f"${f:,.0f}" if f else "—"
    except (TypeError, ValueError):
        return "—"


@app.template_filter("kmoney")
def _kmoney(v) -> str:
    try:
        f = float(v)
        if not f:
            return "—"
        if f >= 1_000_000:
            return f"${f/1_000_000:.1f}M"
        if f >= 1_000:
            return f"${f/1_000:.0f}k"
        return f"${f:.0f}"
    except (TypeError, ValueError):
        return "—"


# ---------- Entrypoint -----------------------------------------------------

def run():
    dl.ensure_files()
    port = int(os.environ.get("PORT", 5050))
    host = os.environ.get("HOST", "127.0.0.1")
    # Auto-open browser unless suppressed
    if os.environ.get("NO_BROWSER") != "1":
        webbrowser.open(f"http://{host}:{port}/")
    print(f"\n  Dashboard running at http://{host}:{port}\n")
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    run()

"""Single entrypoint for cron / manual runs.

    python -m tasks assessor-refresh
    python -m tasks mls-refresh
    python -m tasks leads
    python -m tasks digest
    python -m tasks daily          # assessor-refresh + mls-refresh + leads + digest
"""

from __future__ import annotations

import sys
import typer

from mls_bot.ingest import assessor, mls
from mls_bot.leads import expired, absentee
from mls_bot import digest as digest_mod
from mls_bot import profile as profile_mod
from mls_bot import leadgen as leadgen_mod

app = typer.Typer(add_completion=False)


@app.command("assessor-refresh")
def assessor_refresh():
    n = assessor.refresh()
    typer.echo(f"assessor: upserted {n} parcels")


@app.command("assessor-sample")
def assessor_sample(
    out: str = "data/blacksburg_parcels.jsonl",
    limit: int = typer.Option(0, help="0 = all, or e.g. 200 for a quick peek"),
    jurisdiction: str = typer.Option(
        "",
        help="BLACKSBURG | CHRISTIANSBURG | MONTGOMERY | ALL. Empty = env default.",
    ),
    county: str = typer.Option(
        "MONTGOMERY",
        help="County source key. Run `assessor-sources` to list.",
    ),
):
    """Pull parcels from ArcGIS and write to JSONL. No database needed."""
    stats = assessor.dump_sample(
        out,
        limit=limit or None,
        jurisdiction=jurisdiction or None,
        county=county,
    )
    typer.echo(f"wrote {out}")
    for k, v in stats.items():
        typer.echo(f"  {k:22s} {v}")


@app.command("assessor-sources")
def assessor_sources():
    """List registered county parcel sources."""
    from mls_bot.ingest.sources import SOURCES
    for key, src in sorted(SOURCES.items()):
        typer.echo(f"  {key:18s}  {src.url}")


@app.command("mls-refresh")
def mls_refresh():
    ins, upd = mls.refresh()
    typer.echo(f"mls: {ins} new listings, {upd} updated")


@app.command("leads")
def leads():
    e = expired.detect()
    a = absentee.detect()
    typer.echo(f"leads: {e} expired, {a} absentee")


@app.command("digest")
def digest():
    digest_mod.send()
    typer.echo("digest: sent")


@app.command("profile")
def profile(path: str = "data/blacksburg_parcels.jsonl"):
    """Print a profile of a parcel JSONL dump. No database needed."""
    profile_mod.print_profile(path)


@app.command("top-owners")
def top_owners(
    path: str = "data/blacksburg_parcels.jsonl",
    owner_type: str = typer.Option("person", help="person | entity | govt_or_institution | all"),
    limit: int = 25,
):
    """Rank owners by number of parcels (grouped by owner name)."""
    profile_mod.print_top_owners(path, owner_type=owner_type, limit=limit)


@app.command("top-mailers")
def top_mailers(
    path: str = "data/montgomery_county_parcels.jsonl",
    limit: int = 30,
    include_govt: bool = typer.Option(False, help="Include govt/institutional mail addresses"),
):
    """Rank portfolios by shared mailing address. Same mail = same owner."""
    profile_mod.print_top_by_mail(path, limit=limit, exclude_govt=not include_govt)


@app.command("new-investors")
def new_investors(
    path: str = "data/montgomery_county_parcels.jsonl",
    recency_years: int = typer.Option(3, help="All parcels must be acquired within N years"),
    min_count: int = typer.Option(2, help="Minimum parcels in portfolio"),
    min_distinct_sites: int = typer.Option(2, help="Require parcels to span this many distinct site addresses"),
    min_distinct_dates: int = typer.Option(1, help="Require this many distinct sale dates (2+ = actively accumulating)"),
    group_by: str = typer.Option("mail", help="mail | owner"),
    owner_type: str = typer.Option("person", help="person | entity | all"),
    jurisdiction: str = typer.Option("BLACKSBURG", help="BLACKSBURG | CHRISTIANSBURG | MONTGOMERY | empty for all"),
    limit: int = 30,
):
    """Find owners who started accumulating multiple parcels within the last N years."""
    profile_mod.print_new_investors(
        path,
        recency_years=recency_years,
        min_count=min_count,
        min_distinct_sites=min_distinct_sites,
        min_distinct_dates=min_distinct_dates,
        group_by=group_by,
        owner_type=owner_type,
        jurisdiction=jurisdiction or None,
        limit=limit,
    )


@app.command("leadgen")
def leadgen(
    category: str = typer.Argument(..., help="Category name. Use leadgen-list to see options."),
    path: str = "data/montgomery_county_parcels.jsonl",
    jurisdiction: str = typer.Option("BLACKSBURG", help="BLACKSBURG | CHRISTIANSBURG | MONTGOMERY | ALL"),
    limit: int = typer.Option(50, help="0 = all leads"),
    cfg: list[str] = typer.Option(
        [], "--cfg",
        help="Extra config as KEY=VAL (repeatable). E.g. --cfg tenure_min=3 --cfg tenure_max=7",
    ),
    csv_out: str = typer.Option(
        "", "--csv",
        help="Write CSV to this path instead of printing to console",
    ),
):
    """Run a named lead-category detector against a JSONL parcel dump."""
    if category not in leadgen_mod.REGISTRY:
        typer.echo(f"unknown category: {category}")
        typer.echo(f"available: {', '.join(sorted(leadgen_mod.REGISTRY))}")
        raise typer.Exit(code=1)

    config: dict = {"jurisdiction": jurisdiction}
    for kv in cfg:
        if "=" in kv:
            k, _, v = kv.partition("=")
            config[k.strip()] = v.strip()

    rows = profile_mod._load_rows(path)
    leads_list = leadgen_mod.REGISTRY[category](rows, config)
    sliced = leads_list if limit <= 0 else leads_list[:limit]

    if csv_out:
        n = leadgen_mod.write_leads_csv(csv_out, sliced)
        typer.echo(f"wrote {n} {category} leads to {csv_out}")
    else:
        leadgen_mod.print_leads(category, sliced)


@app.command("leadgen-list")
def leadgen_list():
    """List available lead categories."""
    for name in sorted(leadgen_mod.REGISTRY):
        typer.echo(name)


@app.command("daily")
def daily():
    assessor_refresh()
    mls_refresh()
    leads()
    digest()


@app.command("mls-enrich")
def mls_enrich():
    """Run flood + condition + commute enrichment passes on listings_plus_deeds.jsonl.

    Idempotent. Run after merge-deeds; before analytics + CMA so all
    downstream tools see the enriched columns.
    """
    import subprocess
    typer.echo("\n[enrich 1/3] FEMA flood-zone overlay")
    subprocess.run(["python", "scripts/enrich_listings_flood.py"], check=False, env={**__import__("os").environ, "PYTHONPATH": "src"})
    typer.echo("\n[enrich 2/3] condition + manufactured-home extraction")
    subprocess.run(["python", "scripts/enrich_listings_condition.py"], check=False, env={**__import__("os").environ, "PYTHONPATH": "src"})
    typer.echo("\n[enrich 3/4] commute scoring (VT, Carilion, downtown Bburg, etc.)")
    subprocess.run(["python", "scripts/enrich_listings_commute.py"], check=False, env={**__import__("os").environ, "PYTHONPATH": "src"})
    typer.echo("\n[enrich 4/4] parcel slope + listing photo attachments")
    subprocess.run(["python", "scripts/enrich_listings_attachments.py"], check=False, env={**__import__("os").environ, "PYTHONPATH": "src"})


@app.command("mls-daily")
def mls_daily():
    """Full daily MLS refresh: incremental pull -> merge deeds -> enrich -> analytics -> leads -> alerts.

    Run this on a schedule (Task Scheduler on Windows, cron on Unix). Each
    step is idempotent — safe to re-run on failure.
    """
    typer.echo("=== mls-daily start ===")
    typer.echo("\n[1/6] incremental RETS pull")
    mls_pull_incremental()
    typer.echo("\n[2/6] merge county deed sales")
    merge_deeds()
    typer.echo("\n[3/6] enrich listings (flood + condition + commute)")
    mls_enrich()
    typer.echo("\n[3.5/6] rebuild CMA parquet (mls_lookup.parquet) — was missing; CMA read stale comps")
    mls_rebuild_parquet()
    typer.echo("\n[4/6] rebuild analytics CSVs")
    mls_build_analytics()
    typer.echo("\n[5/6] lead-gen lists (expiring, off-MLS, investor portfolios, builders, probate)")
    mls_leads()
    typer.echo("       expired-listing watchlist")
    mls_expired_watchlist()
    typer.echo("       expired-and-not-relisted (address-deduped)")
    mls_expired_unrelisted()
    typer.echo("       per-neighborhood performance + dominant brokerage")
    mls_neighborhood_stats()
    typer.echo("       neighbor-of-recent-sale outreach")
    mls_neighbor_outreach()
    typer.echo("       owner-dedup + multi-property portfolios")
    nrv_rebuild_owner_dedup()
    typer.echo("       deed-pattern signals (intra-family, flippers)")
    nrv_rebuild_deed_signals()
    typer.echo("       monthly mail-addr snapshot (idempotent within month)")
    nrv_snapshot_mail_addrs()
    typer.echo("\n[6/6] alerts (price drops + status changes, last 7 days)")
    mls_alerts()
    typer.echo("\n[bonus] daily digest HTML")
    mls_digest()
    typer.echo("\n[bonus] index landing page")
    mls_index()
    typer.echo("\n=== mls-daily complete ===")


@app.command("mls-weekly")
def mls_weekly():
    """Weekly tasks: refresh agent/office directory + retrain DOM model.

    Heavier than mls-daily. Run on Sundays via scheduler.
    """
    typer.echo("=== mls-weekly start ===")
    typer.echo("\n[1/2] refresh agent/office directory")
    mls_pull_directory()
    typer.echo("\n[2/2] retrain DOM model")
    mls_train_dom_model()
    typer.echo("\n=== mls-weekly complete ===")


# ----------------------------------------------------------------------------
# NRV MLS analytics — RETS-backed JSONL pipeline + DuckDB analytics.

@app.command("mls-pull-all")
def mls_pull_all():
    """Pull every NRV MLS listing the RETS feed exposes, all 6 classes."""
    from pathlib import Path
    from mls_bot.ingest.rets_pull import pull_all
    field_map = Path("outputs/rets_metadata/field_map.json")
    if not field_map.exists():
        typer.echo("!! field map missing — run scripts/build_field_map.py first")
        raise typer.Exit(code=1)
    summary = pull_all(
        field_map_path=field_map,
        out_listings=Path("data/mls/listings.jsonl"),
        out_pulls_log=Path("data/mls/pulls_log.jsonl"),
    )
    typer.echo(f"pulled {summary['total']} listings in {summary['elapsed_s']}s")
    for cls, n in summary["counts"].items():
        typer.echo(f"  {cls}: {n}")


@app.command("mls-join")
def mls_join():
    """Join MLS listings to county parcel data via parcel_id (LM_Char50_3)."""
    import sys
    sys.path.insert(0, "scripts")
    from join_listings_to_parcels import main as run_join
    raise typer.Exit(code=run_join())


@app.command("mls-watch")
def mls_watch(
    cities: str = typer.Option("", help="Comma-separated cities, e.g. 'Blacksburg,Christiansburg'"),
    classes: str = typer.Option("RE_1", help="Comma-separated property classes (RE_1,LD_3,etc.)"),
    statuses: str = typer.Option("Active,Pending", help="Status categories"),
    min_price: float = typer.Option(0, help="Min list price"),
    max_price: float = typer.Option(0, help="Max list price (0=no cap)"),
    min_beds: int = typer.Option(0),
    max_beds: int = typer.Option(0),
    min_sqft: int = typer.Option(0),
    max_sqft: int = typer.Option(0),
    min_acres: float = typer.Option(0),
    max_acres: float = typer.Option(0),
    zoning_like: str = typer.Option(""),
    subdivision_like: str = typer.Option(""),
    listed_within_days: int = typer.Option(0, help="Limit to listings created in the last N days (0=any)"),
    out: str = typer.Option("", "--out", help="Optional CSV output path"),
):
    """Find active/pending listings matching saved criteria.

    Example:
        python tasks.py mls-watch --cities Blacksburg --max-price 450000 --min-beds 3
    """
    from pathlib import Path
    from mls_bot.analytics.alerts import watch_listings
    out_csv = Path(out) if out else Path(f"outputs/mls_analytics/watch_results.csv")
    n = watch_listings(
        cities=[c.strip() for c in cities.split(",") if c.strip()] or None,
        classes=[c.strip() for c in classes.split(",") if c.strip()],
        statuses=[s.strip() for s in statuses.split(",") if s.strip()],
        min_price=min_price or None,
        max_price=max_price or None,
        min_beds=min_beds or None,
        max_beds=max_beds or None,
        min_sqft=min_sqft or None,
        max_sqft=max_sqft or None,
        min_acres=min_acres or None,
        max_acres=max_acres or None,
        zoning_like=zoning_like or None,
        subdivision_like=subdivision_like or None,
        listed_within_days=listed_within_days or None,
        out_csv=out_csv,
    )
    typer.echo(f"matched {n} listings -> {out_csv}")


@app.command("mls-alerts")
def mls_alerts(
    days: int = typer.Option(7, help="Look-back window in days"),
    only_drops: bool = typer.Option(True, help="Only show price drops (not increases)"),
    min_pct: float = typer.Option(1.0, help="Minimum %% absolute change to surface"),
):
    """Surface recent price changes and status transitions from the history log."""
    from pathlib import Path
    from mls_bot.analytics.alerts import write_recent_price_changes_csv, write_recent_status_changes_csv
    out_dir = Path("outputs/mls_analytics")
    out_dir.mkdir(parents=True, exist_ok=True)
    n = write_recent_price_changes_csv(out_dir / "alerts_price_changes.csv",
                                       days=days, only_drops=only_drops, min_pct_change=min_pct)
    typer.echo(f"  alerts_price_changes.csv: {n} rows")
    n = write_recent_status_changes_csv(out_dir / "alerts_status_changes.csv", days=days)
    typer.echo(f"  alerts_status_changes.csv: {n} rows")


@app.command("mls-pull-incremental")
def mls_pull_incremental():
    """Pull only listings updated since the last successful pull.

    Detects status / price transitions vs. the existing snapshot and writes
    them to data/mls/listings_history.jsonl (append-only).
    """
    from mls_bot.ingest.rets_incremental import pull_incremental
    summary = pull_incremental()
    typer.echo(f"\n=== incremental refresh ===")
    typer.echo(f"  anchor: {summary['anchor']}")
    typer.echo(f"  updates: {summary['total_updates']}")
    typer.echo(f"  history events: {summary['history_events']}")
    typer.echo(f"  elapsed: {summary['elapsed_s']}s")


@app.command("mls-rebuild-parquet")
def mls_rebuild_parquet():
    """Rebuild data/mls_lookup.parquet — the parquet the CMA / valuation engine
    actually queries — from the current richest listings snapshot.

    The incremental RETS pull upserts data/mls/listings.jsonl, and merge-deeds /
    enrich produce listings_plus_deeds.jsonl; this propagates whichever is richest
    into mls_lookup.parquet so comps are never stale. Fast (~seconds): one DuckDB
    projection, no county re-read.
    """
    import sys as _sys
    import duckdb
    _sys.path.insert(0, "scripts")
    from build_parcel_lookup import _build_mls_lookup, _pick_listings_jsonl
    typer.echo(f"  source: {_pick_listings_jsonl()}")
    con = duckdb.connect()
    _build_mls_lookup(con)
    con.close()


@app.command("mls-rebuild-market-index")
def mls_rebuild_market_index():
    """Rebuild data/market_index.parquet — county monthly median $/sqft index
    (S1 trending infrastructure: AVM debias, prior-sale anchors, falling
    markets). Production-only artifact; backtests must use
    mls_bot.analytics.market_index.index_ratio_asof, never this parquet.
    Cheap (~seconds); run after mls-rebuild-parquet whenever comps refresh.
    """
    import sys as _sys
    _sys.path.insert(0, "scripts")
    from build_market_index import main as _run
    raise typer.Exit(code=_run())


@app.command("mls-pull-directory")
def mls_pull_directory():
    """Pull RETS Agent + Office directory (4k+ agents, 600+ offices)."""
    from mls_bot.ingest.rets_directory import pull_directory
    s = pull_directory()
    typer.echo(f"agents: {s['agents']}, offices: {s['offices']} ({s['elapsed_s']}s)")


@app.command("mls-pull-media")
def mls_pull_media(
    statuses: str = typer.Option("Active,Pending", help="Comma-separated status categories to pull photos for"),
):
    """Pull photo URLs from Paragon Media for the given listing statuses.

    Defaults to Active+Pending. Photos remain hosted on Paragon's CDN; we
    only store the URL references in data/mls/listings_media.jsonl.
    """
    from pathlib import Path
    from mls_bot.ingest.rets_media import pull_media
    summary = pull_media(
        listings_path=Path("data/mls/listings.jsonl"),
        out_path=Path("data/mls/listings_media.jsonl"),
        statuses=[s.strip() for s in statuses.split(",") if s.strip()],
    )
    typer.echo(f"pulled photos in {summary['elapsed_s']}s")
    for k, v in summary.items():
        typer.echo(f"  {k}: {v}")


@app.command("merge-deeds")
def merge_deeds():
    """Merge NRV county deed sales (last_sale_date/price) into MLS listings.

    Extends pre-2023 sold history beyond what Paragon's RETS feed retains.
    Outputs data/mls/listings_plus_deeds.jsonl + data/mls/deed_sales_nrv.jsonl.
    """
    import sys
    sys.path.insert(0, "scripts")
    from merge_deed_sales import main as run_merge
    raise typer.Exit(code=run_merge())


@app.command("mls-train-cut-model")
def mls_train_cut_model(
    train_until: str = typer.Option("2025-09-30"),
):
    """Train the price-cut probability classifier."""
    from mls_bot.analytics.price_cut_model import train
    train(train_until=train_until)


@app.command("mls-train-dom-model")
def mls_train_dom_model(
    train_until: str = typer.Option("2025-09-30", help="Train on close_date < this; validate on >="),
    cdom_max: int = typer.Option(180, help="Drop sales with feed_cdom above this (outliers)"),
):
    """Train the predictive DOM model. Writes artifacts to outputs/mls_analytics/dom_model/."""
    from mls_bot.analytics.dom_model import train
    train(train_until=train_until, cdom_max=cdom_max)


@app.command("mls-recommend-price")
def mls_recommend_price(
    parcel_id: str = typer.Option("", "--parcel-id"),
    address: str = typer.Option("", "--address"),
    target_dom: int = typer.Option(14, help="Days target sale window"),
):
    """Recommend a list-price band to hit a target DOM."""
    from mls_bot.analytics.cma import find_subject
    from mls_bot.analytics.dom_model import recommend_price_for_target_dom
    subj = find_subject(parcel_id=parcel_id or None, address=address or None)
    if not subj:
        typer.echo("subject not found"); raise typer.Exit(code=1)
    rec = recommend_price_for_target_dom(subj, target_dom=target_dom,
                                          cohort_median_price=float(subj.get('list_price') or 250000))
    typer.echo(f"Subject: {subj.get('address')} ({subj.get('city')})")
    for k, v in rec.items():
        typer.echo(f"  {k}: {v}")


@app.command("mls-velocity")
def mls_velocity():
    """Build market velocity index (months-of-inventory by city × class)."""
    from pathlib import Path
    from mls_bot.analytics.velocity import write_velocity_csv, headline_summary
    n = write_velocity_csv(Path("outputs/mls_analytics/market_velocity.csv"))
    typer.echo(f"market_velocity.csv: {n} rows")
    for c, cls, moi, label in headline_summary():
        typer.echo(f"  {c:25s}  {cls}  {moi:>5.2f} mo  ({label})")


@app.command("mls-rankings")
def mls_rankings():
    """Build agent + office performance rankings (trailing 24 months)."""
    from pathlib import Path
    from mls_bot.analytics.performance import write_office_rankings_csv, write_agent_rankings_csv
    n = write_office_rankings_csv(Path("outputs/mls_analytics/office_rankings.csv"))
    typer.echo(f"  office_rankings.csv: {n} rows")
    n = write_agent_rankings_csv(Path("outputs/mls_analytics/agent_rankings.csv"))
    typer.echo(f"  agent_rankings.csv: {n} rows")


@app.command("mls-price-cuts")
def mls_price_cuts():
    """Build price-cut waterfall + per-listing cut detail."""
    from pathlib import Path
    from mls_bot.analytics.price_cuts import write_price_cut_waterfall_csv, write_listings_with_cuts_csv
    n = write_price_cut_waterfall_csv(Path("outputs/mls_analytics/price_cut_waterfall.csv"))
    typer.echo(f"  price_cut_waterfall.csv: {n} rows")
    n = write_listings_with_cuts_csv(Path("outputs/mls_analytics/listings_with_cuts.csv"))
    typer.echo(f"  listings_with_cuts.csv: {n} rows")


@app.command("mls-index")
def mls_index():
    """Build the MLS Analytics index landing page (links to every report + CSV)."""
    from mls_bot.analytics.index_page import build_index
    p = build_index()
    typer.echo(f"  index: {p}")


@app.command("mls-digest")
def mls_digest(
    days: int = typer.Option(7, help="Lookback window for status/price events"),
    send: bool = typer.Option(False, "--send", help="Also email it via SMTP"),
):
    """Build the MLS daily digest HTML (and optionally email it)."""
    from mls_bot.analytics.digest import build_digest_html, send_digest_email
    p = build_digest_html(days=days)
    typer.echo(f"  digest html: {p}")
    if send:
        send_digest_email()


@app.command("mls-heatmap")
def mls_heatmap():
    """Build the NRV-wide market heatmap (city × class × 6 metrics)."""
    from mls_bot.analytics.heatmap import render_heatmap
    p = render_heatmap()
    typer.echo(f"  heatmap: {p}")


@app.command("mls-portal")
def mls_portal():
    """Build the single-page buyer-search HTML portal (data embedded; no server needed)."""
    from mls_bot.analytics.buyer_portal import build_portal
    p = build_portal()
    typer.echo(f"  buyer portal: {p}")


@app.command("mls-property")
def mls_property(
    parcel_id: str = typer.Option("", "--parcel-id"),
    address: str = typer.Option("", "--address"),
):
    """Render a per-property history page (all listings + deeds + flags)."""
    from mls_bot.analytics.property_history import render_property_history
    if not (parcel_id or address):
        typer.echo("must specify --parcel-id or --address"); raise typer.Exit(code=1)
    p = render_property_history(parcel_id=parcel_id or None, address=address or None)
    if p:
        typer.echo(f"  property history: {p}")
    else:
        typer.echo("  no records found")


@app.command("mls-property-batch")
def mls_property_batch(
    min_listings: int = typer.Option(2, help="Minimum listing count to qualify"),
    max_n: int = typer.Option(200, help="Max parcels to render"),
):
    """Batch-render history pages for parcels with multiple listings (flips, relists)."""
    from mls_bot.analytics.property_history import render_top_properties
    n = render_top_properties(min_listings=min_listings, max_n=max_n)
    typer.echo(f"  rendered {n} property history pages")


@app.command("mls-bulk-cma")
def mls_bulk_cma(
    cities: str = typer.Option("", help="Comma-separated cities; empty = all"),
    classes: str = typer.Option("RE_1", help="Comma-separated property classes"),
    statuses: str = typer.Option("Active,Pending", help="Status categories to cover"),
    max_n: int = typer.Option(0, help="Max listings (0 = all)"),
):
    """Generate a CMA HTML for every active+pending listing matching filters."""
    from mls_bot.analytics.bulk_cma import generate_bulk_cmas, write_bulk_index, BULK_DIR
    s = generate_bulk_cmas(
        cities=[c.strip() for c in cities.split(",") if c.strip()] or None,
        classes=[c.strip() for c in classes.split(",") if c.strip()],
        statuses=[s.strip() for s in statuses.split(",") if s.strip()],
        max_n=max_n or None,
    )
    typer.echo(f"\ngenerated {s['ok']}/{s['total']} CMAs in {s['elapsed_s']}s ({s['skipped']} skipped)")
    idx = write_bulk_index()
    typer.echo(f"index: {idx}")


@app.command("mls-newsletter")
def mls_newsletter(
    city: str = typer.Option(..., help="City name, e.g. 'Blacksburg'"),
    subdivision: str = typer.Option("ALL", help="Subdivision name; 'ALL' for citywide"),
    period: str = typer.Option(..., help="Quarter, e.g. 'Q1-2026'"),
):
    """Generate a one-page quarterly market-update HTML for a (city, subdivision)."""
    from mls_bot.analytics.newsletter import render_newsletter
    p = render_newsletter(city=city, subdivision=subdivision, period=period)
    typer.echo(f"  newsletter: {p}")


@app.command("mls-subdivisions")
def mls_subdivisions(
    min_sales: int = typer.Option(10, help="Min 5-year closed sales to render a report"),
    max_n: int = typer.Option(120, help="Max subdivisions to render"),
):
    """Render per-subdivision deep-dive HTML reports."""
    from mls_bot.analytics.subdivision import render_top_subdivisions
    n = render_top_subdivisions(min_sales=min_sales, max_n=max_n)
    typer.echo(f"  rendered {n} subdivision reports -> outputs/mls_analytics/subdivisions/")


@app.command("mls-seller-scores")
def mls_seller_scores(
    min_score: int = typer.Option(40, help="Minimum score to include"),
):
    """Build the predictive seller-score CSV (heuristic + FRED rate lock-in + outreach annotation)."""
    from mls_bot.analytics.seller_scoring import score_parcels
    from mls_bot.analytics.outreach import annotate_scores_csv
    n = score_parcels(min_score=min_score)
    typer.echo(f"  seller_scores.csv: {n:,} prospects")
    annotate_scores_csv()


@app.command("mls-train-avm")
def mls_train_avm():
    """Train the AVM (automated valuation model) on closed sales."""
    from mls_bot.analytics.avm import train
    train()


@app.command("mls-value")
def mls_value(
    parcel_id: str = typer.Option("", "--parcel-id"),
    address: str = typer.Option("", "--address"),
):
    """Predict current market value for a parcel (off-market AVM)."""
    from mls_bot.analytics.avm import predict_for_parcel, predict
    from mls_bot.analytics.cma import find_subject
    if parcel_id:
        r = predict_for_parcel(parcel_id)
        if not r:
            typer.echo("parcel not found in MLS data"); raise typer.Exit(1)
        typer.echo(f"  parcel: {parcel_id}")
        typer.echo(f"  subject: {r['subject'].get('address')} {r['subject'].get('city')}")
        typer.echo(f"  AVM predicted value: ${int(r['predicted_value'] or 0):,}")
    elif address:
        s = find_subject(address=address)
        if not s:
            typer.echo("subject not found"); raise typer.Exit(1)
        v = predict(s)
        typer.echo(f"  subject: {s.get('address')} {s.get('city')}")
        typer.echo(f"  AVM predicted value: ${int(v or 0):,}")
    else:
        typer.echo("must specify --parcel-id or --address"); raise typer.Exit(1)


@app.command("mls-saved-searches")
def mls_saved_searches():
    """Run all saved searches.

    Two sources:
      1. YAML at config/saved_searches.yaml (legacy / repo-tracked)
      2. Dashboard SavedSearch table in web/prisma/dev.db (managed via UI)
    """
    from mls_bot.analytics.saved_search import run_all_saved_searches, render_alerts_index
    from mls_bot.analytics.saved_searches_db import run_all_db_searches

    typer.echo("[yaml searches]")
    s = run_all_saved_searches()
    if isinstance(s, dict) and "status" in s:
        typer.echo("  (none configured in config/saved_searches.yaml)")
    else:
        for name, info in s.items():
            typer.echo(f"  {name}: {info['current_n']} current  ({info['new_n']} new, {info['dropped_n']} dropped)")
        p = render_alerts_index()
        typer.echo(f"  index: {p}")

    typer.echo("\n[dashboard searches]")
    try:
        d = run_all_db_searches()
    except FileNotFoundError as e:
        typer.echo(f"  {e}")
        return
    if "_meta" in d:
        typer.echo(f"  ({d['_meta'].get('note', 'none')})")
        return
    for display_id, info in d.items():
        if "error" in info:
            typer.echo(f"  {display_id} [{info['name']}]: ERROR {info['error']}")
        else:
            typer.echo(f"  {display_id} [{info['name']}]: {info['matches']} current")


@app.command("mls-hourly")
def mls_hourly():
    """Hourly refresh: incremental pull + saved-search re-run.

    Designed to be invoked by Windows Task Scheduler every hour. Cheap;
    skips the full analytics regen that mls-daily does.

    To install on Windows (PowerShell, admin):
      $a = New-ScheduledTaskAction -Execute 'python' -Argument 'tasks.py mls-hourly' -WorkingDirectory 'C:\\Users\\zach\\Desktop\\MLS Bot'
      $t = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Hours 1)
      Register-ScheduledTask -TaskName 'MLSHourly' -Action $a -Trigger $t
    """
    typer.echo("=== mls-hourly start ===")
    typer.echo("\n[1/5] incremental RETS pull")
    mls_pull_incremental()
    typer.echo("\n[2/5] merge county deed sales (brings fresh listings into plus-deeds)")
    try:
        merge_deeds()
    except typer.Exit:
        pass  # merge_deeds raises typer.Exit(code) on success
    typer.echo("\n[3/5] enrich (flood + condition + commute) — keep enrich columns present")
    mls_enrich()
    typer.echo("\n[4/6] rebuild mls_lookup.parquet (the parquet the CMA reads)")
    mls_rebuild_parquet()
    typer.echo("\n[5/6] rebuild address search index (the in-app typeahead reads this)")
    mls_build_search_index()
    typer.echo("\n[6/6] re-run saved searches (yaml + dashboard)")
    mls_saved_searches()
    typer.echo("\n=== mls-hourly complete ===")


@app.command("mls-build-search-index")
def mls_build_search_index():
    """Rebuild data/search_index.sqlite — the SQLite+FTS5 address index the Next
    app queries in-process (better-sqlite3) for the property typeahead, replacing
    the old per-keystroke Python spawn. Reads mls_lookup.parquet + parcel_lookup
    .parquet. Run after either parquet changes (wired into mls-hourly)."""
    import subprocess

    r = subprocess.run(
        ["python", "scripts/build_search_index.py"],
        env={**__import__("os").environ, "PYTHONPATH": "src"},
        check=False,
    )
    if r.returncode != 0:
        typer.echo("  [warn] search index build failed", err=True)


@app.command("mls-leads")
def mls_leads(
    expiring_within_days: int = typer.Option(60, help="Days look-ahead for expiry watchlist"),
):
    """Build all 4 lead-gen lists (expiring, expired-then-sold, investor portfolios, builders)."""
    from mls_bot.analytics.leadgen import build_all_leads
    counts = build_all_leads(expiring_within_days=expiring_within_days)
    for k, v in counts.items():
        typer.echo(f"  {k}: {v} leads")


@app.command("mls-build-analytics")
def mls_build_analytics(
    year_min_dom: int = typer.Option(2015, help="Earliest close-year for the DOM cohort table"),
    year_min_fast: int = typer.Option(2018, help="Earliest close-year for fast-sellers"),
    year_min_lag: int = typer.Option(2020, help="Earliest list-year for laggards"),
    min_cohort: int = typer.Option(5, help="Minimum sales required to define a cohort"),
):
    """Generate DOM cohort tables, fast-sellers, laggards, and list-to-sold spread."""
    from pathlib import Path
    from mls_bot.analytics.dom import write_dom_csv, write_dom_by_subdivision_csv
    from mls_bot.analytics.fast_sellers import write_fast_sellers_csv
    from mls_bot.analytics.laggards import write_laggards_csv
    from mls_bot.analytics.spread import write_spread_csv
    from mls_bot.analytics.deed_dom import write_expired_then_sold_csv, write_price_trends_csv
    out = Path("outputs/mls_analytics")
    out.mkdir(parents=True, exist_ok=True)
    n = write_dom_csv(out / "dom_by_cohort.csv", year_min=year_min_dom)
    typer.echo(f"  dom_by_cohort.csv: {n} rows")
    n = write_dom_by_subdivision_csv(out / "dom_by_subdivision.csv", year_min=year_min_fast)
    typer.echo(f"  dom_by_subdivision.csv: {n} rows")
    n = write_fast_sellers_csv(out / "fast_sellers.csv", year_min=year_min_fast, min_cohort=min_cohort)
    typer.echo(f"  fast_sellers.csv: {n} rows")
    n = write_laggards_csv(out / "laggards.csv", year_min=year_min_lag, min_cohort=min_cohort)
    typer.echo(f"  laggards.csv: {n} rows")
    n = write_spread_csv(out / "list_to_sold_spread.csv", year_min=year_min_fast, min_cohort=min_cohort)
    typer.echo(f"  list_to_sold_spread.csv: {n} rows")
    n = write_expired_then_sold_csv(out / "expired_then_sold_offmls.csv", year_min=year_min_dom)
    typer.echo(f"  expired_then_sold_offmls.csv: {n} rows")
    n = write_price_trends_csv(out / "price_trends_with_deeds.csv", year_min=1990)
    typer.echo(f"  price_trends_with_deeds.csv: {n} rows")
    # Tier 3 analytics
    from mls_bot.analytics.velocity import write_velocity_csv
    from mls_bot.analytics.performance import write_office_rankings_csv, write_agent_rankings_csv
    from mls_bot.analytics.price_cuts import write_price_cut_waterfall_csv, write_listings_with_cuts_csv
    n = write_velocity_csv(out / "market_velocity.csv")
    typer.echo(f"  market_velocity.csv: {n} rows")
    n = write_office_rankings_csv(out / "office_rankings.csv")
    typer.echo(f"  office_rankings.csv: {n} rows")
    n = write_agent_rankings_csv(out / "agent_rankings.csv")
    typer.echo(f"  agent_rankings.csv: {n} rows")
    n = write_price_cut_waterfall_csv(out / "price_cut_waterfall.csv")
    typer.echo(f"  price_cut_waterfall.csv: {n} rows")
    n = write_listings_with_cuts_csv(out / "listings_with_cuts.csv")
    typer.echo(f"  listings_with_cuts.csv: {n} rows")


@app.command("mls-neighbor-outreach")
def mls_neighbor_outreach(
    sale_lookback_days: int = typer.Option(14, help="How many days back to look for triggering sales"),
    radius_miles: float = typer.Option(0.5, help="Fallback radius if no subdivision"),
    max_per_sale: int = typer.Option(5, help="Max neighbors surfaced per triggering sale"),
    min_seller_score: int = typer.Option(30, help="Minimum seller_score to include neighbor"),
):
    """Build the neighbor-of-recent-sale outreach list."""
    from mls_bot.analytics.neighbor_outreach import build_neighbor_outreach
    n = build_neighbor_outreach(
        sale_lookback_days=sale_lookback_days,
        radius_miles=radius_miles,
        max_neighbors_per_sale=max_per_sale,
        min_seller_score=min_seller_score,
    )
    typer.echo(f"  neighbor_outreach.csv: {n} rows")


@app.command("nrv-pull-delinquent")
def nrv_pull_delinquent():
    """Parse delinquent-tax PDFs dropped under data/delinquent_tax_pdfs/.

    Filename convention: <county>_<year>.pdf, e.g. MONTGOMERY_2025.pdf.
    Extracts (parcel_id_raw, owner, amount) rows and writes to
    data/parcel_delinquent.jsonl. Cross-references against canonical
    parcel set on the load step.
    """
    from mls_bot.ingest.tax_delinquent import ingest_all, load_delinquent_parcel_ids
    s = ingest_all()
    typer.echo(f"  PDFs found:    {s['pdf_count']}")
    typer.echo(f"  rows parsed:   {s['delinquent_rows_extracted']:,}")
    if s["rows_by_county"]:
        for c, n in sorted(s["rows_by_county"].items()):
            typer.echo(f"    {c}: {n:,}")
    typer.echo(f"  out:           {s['out_path']}")
    matched = load_delinquent_parcel_ids()
    typer.echo(f"  parcels matched canonical: {len(matched):,}")
    if not s["pdf_count"]:
        typer.echo(f"\n  Drop county PDFs into {s['pdf_dir']} and re-run.")


@app.command("nrv-rebuild-deed-signals")
def nrv_rebuild_deed_signals():
    """Compute deed-pattern signals (intra-family, acquisition, flipper) from parcel data."""
    from mls_bot.analytics.deed_signals import build_signals
    s = build_signals()
    typer.echo(f"  parcels scanned:       {s['parcels_scanned']:,}")
    typer.echo(f"  parcels with signals:  {s['parcels_with_signals']:,}")
    typer.echo(f"  flipper owners:        {s['flipper_owners_detected']:,}")
    typer.echo(f"  parcel signals jsonl:  {s['parcel_signals_jsonl']}")
    typer.echo(f"  flippers csv:          {s['flippers_csv']}")


@app.command("nrv-snapshot-mail-addrs")
def nrv_snapshot_mail_addrs():
    """Take a monthly snapshot of every NRV parcel's mailing address.

    Run this monthly (idempotent within a calendar month). Once you have 2+
    snapshots spanning the lookback window, the mail-addr-changed signal
    becomes available to seller_scoring.
    """
    from mls_bot.ingest.parcel_mail_snapshot import take_snapshot, diff_against_baseline
    s = take_snapshot()
    typer.echo(f"  snapshot_date: {s['snapshot_date']}")
    typer.echo(f"  rows scanned:  {s['rows_scanned']:,}")
    typer.echo(f"  rows captured: {s['rows_captured']:,}")
    typer.echo(f"  out:           {s['out_path']}")
    d = diff_against_baseline()
    if "msg" in d:
        typer.echo(f"  diff:          {d['msg']}")
    else:
        typer.echo(f"  baseline:      {d['baseline']}")
        typer.echo(f"  changed:       {d['changed_n']:,} parcels with new mailing address")


@app.command("nrv-rebuild-owner-dedup")
def nrv_rebuild_owner_dedup(
    extended: bool = typer.Option(False, "--extended",
        help="Also include adjacent counties (Roanoke Co, Botetourt, Bedford, etc.) "
             "to catch absentee owners with NRV holdings"),
):
    """Rebuild canonical-owner mapping + multi-property portfolios across NRV parcels."""
    from mls_bot.analytics.owner_dedup import build_canonical
    s = build_canonical(include_extended=extended)
    typer.echo(f"  parcels scanned:       {s['total_parcels_scanned']:,}")
    typer.echo(f"  owners canonicalized:  {s['owners_canonicalized']:,}")
    typer.echo(f"  distinct owners:       {s['distinct_canonical_owners']:,}")
    typer.echo(f"  multi-property owners: {s['owners_with_multiple_parcels']:,}")
    typer.echo(f"  jsonl: {s['owner_canonical_jsonl']}")
    typer.echo(f"  csv:   {s['owner_portfolios_csv']}")


@app.command("dashboard")
def dashboard(
    port: int = typer.Option(5050, help="Local port to bind"),
    no_browser: bool = typer.Option(False, "--no-browser", help="Don't auto-open browser"),
):
    """Start the local realtor dashboard at http://localhost:<port>."""
    import os
    if no_browser:
        os.environ["NO_BROWSER"] = "1"
    os.environ["PORT"] = str(port)
    from mls_bot.dashboard.app import run
    run()


@app.command("mls-campaign-stats")
def mls_campaign_stats():
    """Aggregate the outreach log by `campaign` column; write campaign_performance.csv."""
    from mls_bot.analytics.outreach import campaign_performance
    n = campaign_performance()
    typer.echo(f"  campaign_performance.csv: {n} campaigns")


@app.command("mls-pre-meeting")
def mls_pre_meeting(
    parcel_id: str = typer.Option("", "--parcel-id"),
    address: str = typer.Option("", "--address"),
    city: str = typer.Option("", "--city"),
    email: str = typer.Option(..., "--email", help="Seller's email address"),
    meeting_date: str = typer.Option(..., "--meeting-date", help="YYYY-MM-DD"),
    proposed_price: float = typer.Option(0, "--price",
        help="Proposed list price for cohort logic; 0 = auto-derive"),
    dry_run: bool = typer.Option(False, "--dry-run",
        help="Generate the artifacts but do NOT send the email"),
):
    """Generate + email a pre-meeting CMA to a seller (24h prep)."""
    from mls_bot.analytics.pre_meeting import send_pre_meeting_cma
    if not (parcel_id or address):
        typer.echo("must specify --parcel-id or --address"); raise typer.Exit(1)
    r = send_pre_meeting_cma(
        parcel_id=parcel_id or None,
        address=address or None,
        city=city or None,
        proposed_price=proposed_price or None,
        seller_email=email,
        meeting_date=meeting_date,
        dry_run=dry_run,
    )
    typer.echo(f"\n=== Pre-meeting CMA ===")
    typer.echo(f"  to:       {r['to']}")
    typer.echo(f"  subject:  {r['subject']}")
    typer.echo(f"  HTML:     {r['html']}")
    typer.echo(f"  PDF:      {r['pdf'] or '(none)'}")
    typer.echo(f"  sent:     {'yes' if r['sent'] else ('DRY-RUN' if dry_run else 'no — SMTP creds missing')}")
    if dry_run or not r["sent"]:
        typer.echo(f"\n--- email body preview ---\n{r['preview_body']}")


@app.command("mls-expired-watchlist")
def mls_expired_watchlist(
    lookback_days: int = typer.Option(30, help="How far back to look for expirations"),
    min_score: int = typer.Option(10, help="Minimum re-list propensity score to include"),
):
    """Build the expired-listing watchlist (relist-pitch targets)."""
    from mls_bot.analytics.expired_watchlist import build_expired_watchlist
    n = build_expired_watchlist(lookback_days=lookback_days, min_score=min_score)
    typer.echo(f"  expired_watchlist.csv: {n} rows")


@app.command("mls-expired-unrelisted")
def mls_expired_unrelisted(
    lookback_days: int = typer.Option(28, help="Window to consider 'recent' expirations"),
):
    """Build the list of expireds NOT relisted (deduped by normalized address)."""
    from mls_bot.analytics.expired_unrelisted import build_expired_unrelisted
    n = build_expired_unrelisted(lookback_days=lookback_days)
    typer.echo(f"  expired_unrelisted.csv: {n} listings")


@app.command("mls-neighborhood-stats")
def mls_neighborhood_stats(
    city: str = typer.Option("Blacksburg", help="City to summarize (one CSV per city)"),
):
    """Per-subdivision performance + dominant brokerage / agent IDs."""
    from mls_bot.analytics.neighborhoods import build_neighborhood_stats
    n = build_neighborhood_stats(city=city)
    typer.echo(f"  neighborhoods_{city.lower()}.csv: {n} subdivisions")


@app.command("mls-mail-merge")
def mls_mail_merge(
    theme: str = typer.Option("equity_pitch",
        help="One of: equity_pitch, tenure_pitch, expired_relist, estate_pitch"),
    score_min: int = typer.Option(60, help="Minimum seller_score to include"),
    max_n: int = typer.Option(100, help="Max letters in this batch"),
    base_url: str = typer.Option("",
        help="Public URL prefix for landing pages (QR + 'private report' link). "
             "Empty -> relative path."),
    no_pdf: bool = typer.Option(False, "--no-pdf", help="Skip PDF rendering (HTML only)"),
    campaign: str = typer.Option("",
        help="Campaign tag for outreach tracking. Empty -> auto: <theme>_<YYYYMM>"),
):
    """Generate a batch of personalized listing-acquisition letters from seller_scores.csv."""
    from mls_bot.analytics.mail_merge import generate_letters
    summary = generate_letters(
        theme=theme,
        score_min=score_min,
        max_n=max_n,
        base_url=base_url,
        render_pdfs=not no_pdf,
        campaign=campaign or None,
    )
    if not summary.get("n"):
        typer.echo(f"  no letters generated: {summary.get('msg','no matches')}")
        return
    typer.echo(f"\n=== Mail merge: {summary['theme']} ===")
    typer.echo(f"  batch:     {summary['batch_id']}")
    typer.echo(f"  letters:   {summary['n']}  (HTML: {summary['n_html']}, PDF: {summary['n_pdf']})")
    typer.echo(f"  out dir:   {summary['batch_dir']}")
    typer.echo(f"  index:     {summary['index_csv']}")


@app.command("cma-classic")
def cma_classic(
    price: float = typer.Option(..., "--price", help="Proposed list price"),
    parcel_id: str = typer.Option("", "--parcel-id"),
    address: str = typer.Option("", "--address"),
    city: str = typer.Option("", "--city"),
    out: str = typer.Option("", "--out", help="HTML output path; defaults to outputs/mls_analytics/cma_<id>_<ts>.html"),
    pdf: bool = typer.Option(False, "--pdf", help="Also render a PDF (uses Edge headless on Windows)"),
    deck: bool = typer.Option(False, "--deck", help="Also render a presenter-style slide deck"),
):
    """Detailed price-validation CMA with charts + model predictions.

    For a branded one-pager ready for client delivery, see ``cma`` instead.
    """
    from datetime import datetime
    from pathlib import Path
    from mls_bot.analytics.cma import cma_for, render_html, render_pdf, render_deck
    if not (parcel_id or address):
        typer.echo("must specify --parcel-id or --address"); raise typer.Exit(code=1)
    report = cma_for(
        parcel_id=parcel_id or None,
        address=address or None,
        city=city or None,
        proposed_price=price,
    )
    if "error" in report:
        typer.echo(f"!! {report['error']}"); raise typer.Exit(code=1)
    if not out:
        sid = parcel_id if parcel_id else address.replace(" ", "_").replace("/", "_")[:30]
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = f"outputs/mls_analytics/cma_{sid}_{ts}.html"
    p = render_html(report, Path(out))
    typer.echo(f"\n=== CMA: {report['subject'].get('address','(no address)')} ===")
    typer.echo(f"  Proposed: ${price:,.0f}  ->  cohort percentile p{report['cohort_percentile_for_price']}")
    if report.get("expected_sold_price"):
        typer.echo(f"  Expected sold: ${report['expected_sold_price']:,.0f}")
    cohort = report.get("cohort") or {}
    if cohort.get("median_dom") is not None:
        typer.echo(f"  Cohort: n={cohort.get('n')}  median DOM {round(cohort.get('median_dom') or 0)}d  "
                   f"(p25 {round(cohort.get('p25_dom') or 0)}, p75 {round(cohort.get('p75_dom') or 0)})")
    typer.echo(f"  Verdict: {report.get('verdict','')}")
    typer.echo(f"  Report: {p}")
    if pdf:
        pdf_path = render_pdf(p)
        if pdf_path:
            typer.echo(f"  PDF:    {pdf_path}")
        else:
            typer.echo(f"  PDF:    (auto-generation failed; open the HTML and Ctrl+P -> Save as PDF)")
    if deck:
        deck_path = Path(str(p).replace(".html", "_deck.html"))
        render_deck(report, deck_path)
        typer.echo(f"  Deck:   {deck_path}")


@app.command("cma")
def cma(
    address: str = typer.Argument(..., help="Subject property address (e.g. \"7423 Floyd Highway N\")"),
    brand: str = typer.Option("ratifyly", "--brand", "-b", help="Brand profile name from config/brands/"),
    agent: str = typer.Option("", "--agent", "-a", help="Override the brand's default agent name"),
    parcel_id: str = typer.Option("", "--parcel-id", help="Disambiguate via parcel_id when address is ambiguous"),
    comps: str = typer.Option("", "--comps", help="Comma-separated comp addresses to force-include"),
    months: int = typer.Option(24, "--months", help="Closed-sale lookback window for comp pool"),
    n: int = typer.Option(6, "-n", help="Target number of comps"),
    allow_multi_page: bool = typer.Option(False, "--allow-multi-page", help="Skip the auto-fit single-page enforcement"),
    ai_hygiene: bool = typer.Option(True, "--ai-hygiene/--no-ai-hygiene", help="LLM comp-hygiene reviewer — default ON; needs ANTHROPIC_API_KEY, else falls back to deterministic"),
    rec_price: int = typer.Option(0, "--rec-price", help="Pin an explicit recommended list price on the report (e.g. 695000)"),
    sqft: int = typer.Option(0, "--sqft", help="Override the subject's finished sqft (e.g. include a finished basement)"),
    open_pdf: bool = typer.Option(True, "--open/--no-open", help="Open the resulting PDF when done"),
):
    """Generate a branded one-page CMA PDF in ~15 seconds.

    Pulls the subject from MLS, scores a similarity-weighted comp set, fills
    the active brand template, and renders a single-page PDF via headless
    Chrome with auto-fit fallback if the first render overflows.
    """
    import sys
    from pathlib import Path
    _here = Path(__file__).resolve().parent
    if str(_here / "scripts") not in sys.path:
        sys.path.insert(0, str(_here / "scripts"))
    from build_cma import build_cma

    overrides = [s.strip() for s in comps.split(",")] if comps else None
    try:
        r = build_cma(
            address=address or None,
            parcel_id=parcel_id or None,
            brand_name=brand,
            agent_name=agent or None,
            comp_overrides=overrides,
            n_comps=n,
            months_back=months,
            allow_multi_page=allow_multi_page,
            ai_hygiene=ai_hygiene,
            subject_sqft=sqft or None,
            recommended_price=rec_price or None,
        )
    except ValueError as e:
        typer.echo(f"!! {e}")
        raise typer.Exit(code=1)

    typer.echo(f"\n=== {brand.title()} CMA: {r.subject_address} ===")
    typer.echo(f"  Value range:   ${r.value_low:,} – ${r.estimated_value:,} – ${r.value_high:,}")
    typer.echo(f"  Comp set:      {r.comp_count} comps")
    typer.echo(f"  Page count:    {r.pages}" + (f"  (auto-fit attempts: {r.autofit_attempts})" if r.autofit_attempts else ""))
    typer.echo(f"  Elapsed:       {r.elapsed_seconds:.1f}s")
    typer.echo(f"  HTML:          {r.html_path}")
    typer.echo(f"  PDF:           {r.pdf_path}")
    if open_pdf:
        import subprocess
        try:
            if sys.platform == "win32":
                import os
                os.startfile(r.pdf_path)
            elif sys.platform == "darwin":
                subprocess.run(["open", str(r.pdf_path)], check=False)
            else:
                subprocess.run(["xdg-open", str(r.pdf_path)], check=False)
        except OSError:
            pass


@app.command("cma-brands")
def cma_brands():
    """List the available brand profiles in config/brands/."""
    from mls_bot.brand import available_brands
    names = available_brands()
    if not names:
        typer.echo("No brands configured. Add YAML files under config/brands/.")
        return
    typer.echo("Available brand profiles:")
    for n in names:
        typer.echo(f"  - {n}")


@app.command("property-lookup")
def property_lookup(
    query: str = typer.Argument(..., help="Address or owner-name fragment to search for"),
    limit: int = typer.Option(8, "-n", "--limit", help="Max results"),
):
    """Search MLS + assessor parcels for properties matching the query.

    Quick sanity check before generating a CMA. If a property shows up here it
    can be passed straight to ``python -m tasks cma <address>``.
    """
    from mls_bot.analytics.property_lookup import search_properties
    results = search_properties(query, limit=limit)
    if not results:
        typer.echo(f"No matches for {query!r}.")
        raise typer.Exit(code=1)
    for i, m in enumerate(results, 1):
        line1 = f"{i:2}. [{m.source:6s}] {m.address}"
        if m.city:
            line1 += f"  ({m.city}, {m.county})"
        typer.echo(line1)
        bits = []
        if m.sqft:
            bits.append(f"{int(m.sqft):,} sf")
        if m.acres:
            bits.append(f"{m.acres:.2f} ac")
        if m.year_built and 1800 < m.year_built < 2100:
            bits.append(f"built {int(m.year_built)}")
        if m.bedrooms and m.full_baths:
            bits.append(f"{int(m.bedrooms)}bd/{int(m.full_baths)}ba")
        if m.owner:
            bits.append(f"owner {m.owner[:30]}")
        if m.last_sale_price and m.last_sale_date:
            bits.append(f"last sold {str(m.last_sale_date)[:10]} ${int(m.last_sale_price):,}")
        if m.list_price and m.status == "Active":
            bits.append(f"list ${int(m.list_price):,}")
        typer.echo(f"    {m.status:10s} · " + " · ".join(bits) + f"  [parcel {m.parcel_id}]")


if __name__ == "__main__":
    app()

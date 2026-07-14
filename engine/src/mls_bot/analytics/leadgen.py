"""Lead-gen layer — surfaces actionable lists from the MLS+parcel database.

Each function writes a CSV under outputs/mls_analytics/leads/ and returns the
row count. Each list answers a specific outreach scenario:

  expiring_soon       — listings expiring in next N days (relist pitch)
  expired_then_sold   — past listings that sold off-MLS (FSBO conversion)
  investor_portfolios — LLC/entity-owned multi-listing groupings
  new_builders        — recently-sold parcels by recurring buyers (likely flippers/builders)
"""

from __future__ import annotations

import re
from pathlib import Path

from .db import connect


LEADS_DIR = Path("outputs/mls_analytics/leads")


_ENTITY_PATTERN = re.compile(
    r"\b(LLC|L\.L\.C\.|INC\b|CORP\b|CORPORATION|PARTNERSHIP|LP\b|LLP\b|"
    r"TRUST\b|HOLDINGS|PROPERTIES|REALTY|INVEST|CAPITAL|GROUP\b|"
    r"VENTURES|ASSOCIATES|ESTATES|DEVELOPMENT|BUILDERS|CONSTRUCTION|"
    r"LIMITED|FAMILY|LIVING)\b",
    re.IGNORECASE,
)


def _is_entity(name: str | None) -> bool:
    if not name:
        return False
    return bool(_ENTITY_PATTERN.search(name))


def write_expiring_soon_csv(out_path: Path = LEADS_DIR / "expiring_soon.csv",
                             *, within_days: int = 60) -> int:
    """Active listings whose expiration_date is within the next N days.

    These are pitch targets for a re-list — the existing listing will fall off
    or have to be re-uploaded. Often coincides with a price reduction.
    """
    con = connect()
    sql = f"""
    SELECT
        listing_id, mls_number, _class,
        UPPER(TRIM(city)) AS city, address, subdivision,
        TRY_CAST(list_price AS DOUBLE) AS list_price,
        TRY_CAST(original_list_price AS DOUBLE) AS original_price,
        TRY_CAST(list_date AS DATE) AS list_date,
        TRY_CAST(expiration_date AS DATE) AS expiration_date,
        DATEDIFF('day', CURRENT_DATE, TRY_CAST(expiration_date AS DATE)) AS days_to_expire,
        DATEDIFF('day', TRY_CAST(list_date AS DATE), CURRENT_DATE) AS days_active,
        bedrooms, full_baths, sqft, year_built, zoning,
        list_office_name,
        parcel_owner1, parcel_assessed_total, parcel_owner_occupied,
        ROUND((TRY_CAST(list_price AS DOUBLE) - TRY_CAST(original_list_price AS DOUBLE))
              / NULLIF(TRY_CAST(original_list_price AS DOUBLE), 0) * 100, 2) AS pct_off_orig,
        public_remarks
    FROM listings
    WHERE status_category = 'Active'
      AND TRY_CAST(expiration_date AS DATE) IS NOT NULL
      AND TRY_CAST(expiration_date AS DATE) BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '{within_days} days'
    ORDER BY days_to_expire ASC, days_active DESC
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    con.sql(f"COPY ({sql}) TO '{out_path.as_posix()}' WITH (FORMAT CSV, HEADER)")
    return con.execute(f"SELECT count(*) FROM read_csv_auto('{out_path.as_posix()}')").fetchone()[0]


def _post_add_skip_trace_to_csv(csv_path: Path, owner_col: str, city_col: str | None = None) -> None:
    """Read a CSV, add skip-trace URL columns based on owner_col, rewrite in place."""
    import csv as _csv
    if not csv_path.exists():
        return
    rows: list[dict] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = _csv.DictReader(f)
        for row in reader:
            owner = row.get(owner_col) or ""
            city = (row.get(city_col) or "") if city_col else ""
            urls = _build_skip_trace_urls(owner, city=city)
            row.update(urls)
            rows.append(row)
    if not rows:
        return
    fields = list(rows[0].keys())
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def write_expired_then_sold_leads_csv(
    out_path: Path = LEADS_DIR / "expired_then_sold_leads.csv",
    *, within_months: int = 24,
) -> int:
    """Past sellers whose MLS listing expired but who later sold off-MLS via deed.

    These are people who fired their previous agent and either FSBO'd or sold
    privately. Strong outreach targets if they bought elsewhere they may want
    representation again.
    """
    con = connect()
    sql = f"""
    WITH expired AS (
        SELECT listing_id, _class,
               UPPER(TRIM(city)) AS city,
               address, subdivision,
               TRY_CAST(list_date AS DATE) AS list_date,
               TRY_CAST(off_market_date AS DATE) AS off_market_date,
               TRY_CAST(original_list_price AS DOUBLE) AS original_price,
               TRY_CAST(list_price AS DOUBLE) AS final_list_price,
               TRY_CAST(deed_last_sale_date AS DATE) AS deed_sale_date,
               TRY_CAST(deed_last_sale_price AS DOUBLE) AS deed_sale_price,
               parcel_owner1, parcel_id,
               bedrooms, full_baths, sqft, year_built,
               list_office_name
        FROM listings
        WHERE status_category IN ('Expired/Cancelled', 'Withdrawn')
          AND TRY_CAST(deed_last_sale_date AS DATE) IS NOT NULL
          AND TRY_CAST(deed_last_sale_price AS DOUBLE) > 5000
    )
    SELECT
        listing_id, _class, city, address, subdivision,
        list_date, off_market_date, deed_sale_date, deed_sale_price,
        original_price, final_list_price,
        ROUND(deed_sale_price / NULLIF(original_price, 0), 4) AS pct_of_original,
        DATEDIFF('day', list_date, deed_sale_date) AS days_listed_to_deed,
        bedrooms, full_baths, sqft, year_built,
        parcel_owner1, parcel_id, list_office_name
    FROM expired
    WHERE deed_sale_date >= COALESCE(off_market_date, list_date)
      AND deed_sale_date >= CURRENT_DATE - INTERVAL '{within_months} months'
    ORDER BY deed_sale_date DESC
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    con.sql(f"COPY ({sql}) TO '{out_path.as_posix()}' WITH (FORMAT CSV, HEADER)")
    return con.execute(f"SELECT count(*) FROM read_csv_auto('{out_path.as_posix()}')").fetchone()[0]


def _scc_search_url(name: str) -> str:
    """Deep-link to the VA SCC business entity search for an LLC/Inc name.

    The SCC's clerkinfo.scc.virginia.gov interface accepts a search-name query.
    Click-through reveals registered agent + officers + status — the "pierce"
    info that lets you find a human to contact behind an LLC. No API; this is
    a one-click handoff to the official lookup.
    """
    if not name:
        return ""
    import urllib.parse as _p
    q = _p.quote(name.strip())
    return f"https://cis.scc.virginia.gov/EntitySearch/EntitySearchByName?searchName={q}"


def _build_skip_trace_urls(owner: str | None, city: str | None = None,
                            state: str = "VA") -> dict:
    """Return a dict of click-through deep-links for skip-tracing an owner.

    Person owners → Whitepages, TruePeopleSearch, FastPeopleSearch, LinkedIn.
    Entity owners → VA SCC, OpenCorporates, Google "registered agent".
    All free, all one-click — no scraping.
    """
    if not owner:
        return {"scc_lookup_url": "", "whitepages_url": "", "true_people_url": "",
                "linkedin_url": "", "google_url": ""}
    import urllib.parse as _p
    is_entity = bool(_ENTITY_PATTERN.search(owner))
    name_q = _p.quote(owner.strip())
    name_dashed = _p.quote(owner.strip().replace(",", "").replace("/", " "))
    city_part = _p.quote(city.strip()) if city else ""

    out = {
        "scc_lookup_url": _scc_search_url(owner) if is_entity else "",
        "whitepages_url": (
            f"https://www.whitepages.com/name/{name_dashed.replace(' ', '-')}/{city_part}-{state}"
            if not is_entity else ""
        ),
        "true_people_url": (
            f"https://www.truepeoplesearch.com/results?name={name_q}&citystatezip={city_part}%20{state}"
            if not is_entity else ""
        ),
        "linkedin_url": (
            f"https://www.linkedin.com/search/results/people/?keywords={name_q}"
            if is_entity or owner else ""
        ),
        "google_url": (
            f"https://www.google.com/search?q={name_q}+%22registered+agent%22+Virginia"
            if is_entity else
            f"https://www.google.com/search?q={name_q}+{city_part}+{state}"
        ),
    }
    return out


def write_investor_portfolios_csv(
    out_path: Path = LEADS_DIR / "investor_portfolios.csv",
    *, min_listings: int = 2,
) -> int:
    """Owners (parcel-side) with multiple MLS listings — likely investors / LLCs.

    Surfaces:
      - LLC / Inc / Properties owners who have 2+ active or recent listings
      - Lifetime activity per owner (closed in last 24mo + active now)
    """
    con = connect()
    sql = f"""
    WITH owner_activity AS (
        SELECT
            UPPER(TRIM(parcel_owner1)) AS owner,
            count(*) AS total_listings,
            sum(CASE WHEN status_category='Active' THEN 1 ELSE 0 END) AS n_active,
            sum(CASE WHEN status_category='Pending' THEN 1 ELSE 0 END) AS n_pending,
            sum(CASE WHEN status_category='Closed'
                     AND TRY_CAST(close_date AS DATE) >= CURRENT_DATE - INTERVAL '24 months'
                     THEN 1 ELSE 0 END) AS n_closed_24mo,
            sum(CASE WHEN status_category IN ('Expired/Cancelled', 'Withdrawn') THEN 1 ELSE 0 END) AS n_expired,
            ROUND(SUM(TRY_CAST(sold_price AS DOUBLE)) FILTER (
                  WHERE status_category='Closed'
                    AND TRY_CAST(close_date AS DATE) >= CURRENT_DATE - INTERVAL '24 months'), 0) AS sold_volume_24mo,
            ROUND(MEDIAN(TRY_CAST(list_price AS DOUBLE)) FILTER (
                  WHERE status_category IN ('Active', 'Pending')), 0) AS active_median_price,
            string_agg(DISTINCT UPPER(TRIM(city)), ', ' ORDER BY UPPER(TRIM(city))) AS cities,
            string_agg(DISTINCT _class, ', ' ORDER BY _class) AS classes_mix
        FROM listings
        WHERE parcel_owner1 IS NOT NULL AND TRIM(parcel_owner1) != ''
        GROUP BY UPPER(TRIM(parcel_owner1))
        HAVING count(*) >= {min_listings}
    )
    SELECT *,
        CASE
          WHEN regexp_matches(owner, '\\b(LLC|L\\.L\\.C\\.|INC|CORP|CORPORATION|LP|LLP|HOLDINGS|PROPERTIES|REALTY|INVESTMENTS|CAPITAL|VENTURES|ASSOCIATES|DEVELOPMENT|BUILDERS|CONSTRUCTION)\\b')
            THEN 'entity'
          WHEN regexp_matches(owner, '\\b(TRUST|FAMILY|LIVING)\\b') THEN 'trust_or_family'
          ELSE 'person'
        END AS owner_type
    FROM owner_activity
    ORDER BY (n_active + n_pending) DESC, total_listings DESC
    """
    # Materialize, add full skip-trace deep-link columns (SCC, Whitepages,
    # TruePeopleSearch, LinkedIn, Google). One-click handoff to free lookups.
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows = con.execute(sql).fetchdf()

    def _expand(r):
        # Use the first city in the cities string as a hint for skip-trace
        first_city = (r.get("cities") or "").split(",")[0].strip()
        urls = _build_skip_trace_urls(r["owner"], city=first_city)
        return list(urls.values())

    url_cols = ["scc_lookup_url", "whitepages_url", "true_people_url", "linkedin_url", "google_url"]
    rows[url_cols] = rows.apply(_expand, axis=1, result_type="expand")
    rows.to_csv(out_path, index=False, encoding="utf-8-sig")
    return len(rows)


def write_new_builders_csv(
    out_path: Path = LEADS_DIR / "new_builders.csv",
    *, min_listings: int = 3,
) -> int:
    """Frequent SELLERS in the last 24 months who appear to be flippers/builders.

    Heuristic: a `parcel_owner1` (the person who SOLD a recent listing) appears
    as the seller of 3+ listings within the last 24 months — and has at least
    one active listing now.

    These are ongoing-business sellers (builders, flippers, investors selling
    inventory). Useful for vendor outreach (lenders, contractors) or buyer's-
    agent introductions.
    """
    con = connect()
    sql = f"""
    WITH activity AS (
        SELECT
            UPPER(TRIM(parcel_owner1)) AS owner,
            sum(CASE WHEN status_category='Closed'
                     AND TRY_CAST(close_date AS DATE) >= CURRENT_DATE - INTERVAL '24 months'
                     THEN 1 ELSE 0 END) AS n_closed_24mo,
            sum(CASE WHEN status_category IN ('Active','Pending') THEN 1 ELSE 0 END) AS n_active_now,
            ROUND(MEDIAN(COALESCE(TRY_CAST(feed_cdom AS INT), TRY_CAST(feed_dom AS INT)))
                  FILTER (WHERE status_category='Closed'), 1) AS dom_median,
            ROUND(SUM(TRY_CAST(sold_price AS DOUBLE))
                  FILTER (WHERE status_category='Closed'
                          AND TRY_CAST(close_date AS DATE) >= CURRENT_DATE - INTERVAL '24 months'), 0) AS sold_volume,
            string_agg(DISTINCT UPPER(TRIM(city)), ', ' ORDER BY UPPER(TRIM(city))) AS cities,
            string_agg(DISTINCT _class, ', ' ORDER BY _class) AS classes
        FROM listings
        WHERE parcel_owner1 IS NOT NULL AND TRIM(parcel_owner1) != ''
        GROUP BY UPPER(TRIM(parcel_owner1))
    )
    SELECT *
    FROM activity
    WHERE n_closed_24mo >= {min_listings}
    ORDER BY (n_closed_24mo + n_active_now) DESC, sold_volume DESC NULLS LAST
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    con.sql(f"COPY ({sql}) TO '{out_path.as_posix()}' WITH (FORMAT CSV, HEADER)")
    return con.execute(f"SELECT count(*) FROM read_csv_auto('{out_path.as_posix()}')").fetchone()[0]


def build_all_leads(*, expiring_within_days: int = 60) -> dict[str, int]:
    LEADS_DIR.mkdir(parents=True, exist_ok=True)
    counts = {}
    counts["expiring_soon"] = write_expiring_soon_csv(within_days=expiring_within_days)
    counts["expired_then_sold"] = write_expired_then_sold_leads_csv()
    counts["investor_portfolios"] = write_investor_portfolios_csv()
    counts["new_builders"] = write_new_builders_csv()
    try:
        from .probate import write_probate_signals_csv
        counts["probate_signals"] = write_probate_signals_csv()
    except Exception as e:
        print(f"  [leadgen] probate signals unavailable: {e}")
        counts["probate_signals"] = 0
    # Post-pass: enrich every lead CSV with skip-trace deep-links so each row
    # has clickable lookup URLs (SCC for entities, Whitepages/TruePeople/LinkedIn/Google).
    _post_add_skip_trace_to_csv(LEADS_DIR / "expired_then_sold_leads.csv",
                                  owner_col="parcel_owner1", city_col="city")
    _post_add_skip_trace_to_csv(LEADS_DIR / "new_builders.csv",
                                  owner_col="owner", city_col="cities")
    return counts

"""Listing-side agent/office performance ranking — trailing 24 months.

Metrics per agent / office:
  - closed_n, dollar_volume, avg_sold, median_sold
  - dom_median, dom_p25, sold_to_orig_median
  - expired_n, expiry_rate
  - top_city (most-active jurisdiction)
  - class_mix (RE/MF/LD/CM/FM/RN counts)

Outputs:
  outputs/mls_analytics/office_rankings.csv  (≥20 closed listings)
  outputs/mls_analytics/agent_rankings.csv   (≥10 closed listings)
"""

from __future__ import annotations

from pathlib import Path

from .db import connect


_MIN_OFFICE = 20
_MIN_AGENT = 10


def _ranking_sql(group_field: str, min_n: int) -> str:
    return f"""
    WITH base AS (
        SELECT
            COALESCE({group_field}, '(unknown)') AS grp,
            _class, UPPER(TRIM(city)) AS city,
            status_category,
            TRY_CAST(sold_price AS DOUBLE) AS sold_price,
            TRY_CAST(original_list_price AS DOUBLE) AS orig_price,
            COALESCE(TRY_CAST(feed_cdom AS INT), TRY_CAST(feed_dom AS INT)) AS dom,
            TRY_CAST(close_date AS DATE) AS close_date,
            TRY_CAST(off_market_date AS DATE) AS off_market_date
        FROM listings
        WHERE (
            (status_category = 'Closed'
              AND TRY_CAST(close_date AS DATE) >= CURRENT_DATE - INTERVAL '730 days')
            OR
            (status_category IN ('Expired/Cancelled','Withdrawn')
              AND TRY_CAST(off_market_date AS DATE) >= CURRENT_DATE - INTERVAL '730 days')
        )
    ),
    closed AS (
        SELECT grp,
               COUNT(*) AS closed_n,
               SUM(sold_price) AS dollar_volume,
               ROUND(AVG(sold_price), 0) AS avg_sold,
               ROUND(MEDIAN(sold_price), 0) AS median_sold,
               ROUND(MEDIAN(dom), 1) AS dom_median,
               ROUND(QUANTILE_CONT(dom, 0.25), 1) AS dom_p25,
               ROUND(MEDIAN(sold_price / NULLIF(orig_price, 0)), 4) AS sold_to_orig_median,
               -- top city
               (SELECT b2.city FROM base b2 WHERE b2.grp=b.grp AND b2.status_category='Closed'
                GROUP BY b2.city ORDER BY count(*) DESC LIMIT 1) AS top_city,
               -- class mix
               SUM(CASE WHEN _class='RE_1' THEN 1 ELSE 0 END) AS n_RE,
               SUM(CASE WHEN _class='LD_3' THEN 1 ELSE 0 END) AS n_LD,
               SUM(CASE WHEN _class='MF_2' THEN 1 ELSE 0 END) AS n_MF,
               SUM(CASE WHEN _class='CM_4' THEN 1 ELSE 0 END) AS n_CM,
               SUM(CASE WHEN _class='FM_5' THEN 1 ELSE 0 END) AS n_FM,
               SUM(CASE WHEN _class='RN_6' THEN 1 ELSE 0 END) AS n_RN
        FROM base b
        WHERE status_category='Closed' AND sold_price > 0
        GROUP BY grp
    ),
    expired AS (
        SELECT grp, COUNT(*) AS expired_n
        FROM base
        WHERE status_category IN ('Expired/Cancelled','Withdrawn')
        GROUP BY grp
    )
    SELECT
        c.grp,
        c.closed_n,
        ROUND(c.dollar_volume, 0) AS dollar_volume,
        c.avg_sold, c.median_sold,
        c.dom_median, c.dom_p25,
        ROUND(c.sold_to_orig_median * 100, 2) AS pct_of_orig_list,
        COALESCE(e.expired_n, 0) AS expired_n,
        ROUND(COALESCE(e.expired_n, 0) * 1.0 / NULLIF(c.closed_n + COALESCE(e.expired_n, 0), 0), 4) AS expiry_rate,
        c.top_city,
        c.n_RE, c.n_LD, c.n_MF, c.n_CM, c.n_FM, c.n_RN
    FROM closed c
    LEFT JOIN expired e USING (grp)
    WHERE c.closed_n >= {min_n}
    ORDER BY c.dollar_volume DESC
    """


def write_office_rankings_csv(out_path: Path, *, min_n: int = _MIN_OFFICE) -> int:
    con = connect()
    sql = _ranking_sql("list_office_name", min_n)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    con.sql(f"COPY ({sql}) TO '{out_path.as_posix()}' WITH (FORMAT CSV, HEADER)")
    return con.execute(f"SELECT count(*) FROM read_csv_auto('{out_path.as_posix()}')").fetchone()[0]


def write_agent_rankings_csv(out_path: Path, *, min_n: int = _MIN_AGENT) -> int:
    """Rank agents by listing volume. Joins agents.jsonl + offices.jsonl
    when available so the output has names instead of numeric IDs.
    """
    from pathlib import Path as _Path
    con = connect()
    base_sql = _ranking_sql("CAST(list_agent AS VARCHAR)", min_n)

    agents_path = _Path("data/mls/agents.jsonl")
    offices_path = _Path("data/mls/offices.jsonl")
    if agents_path.exists() and offices_path.exists():
        con.execute(f"""
            CREATE OR REPLACE VIEW _agents AS
            SELECT * FROM read_json_auto('{agents_path.as_posix()}',
                format='newline_delimited', union_by_name=true, sample_size=-1)
        """)
        con.execute(f"""
            CREATE OR REPLACE VIEW _offices AS
            SELECT * FROM read_json_auto('{offices_path.as_posix()}',
                format='newline_delimited', union_by_name=true, sample_size=-1)
        """)
        sql = f"""
        WITH r AS ({base_sql})
        SELECT
            r.grp AS agent_id,
            TRIM(COALESCE(a.U_UserFirstName,'') || ' ' || COALESCE(a.U_UserLastName,'')) AS agent_name,
            o.O_OrganizationName AS office_name,
            a.U_Email AS agent_email,
            a.U_PhoneNumber1 AS agent_phone,
            r.closed_n, r.dollar_volume, r.avg_sold, r.median_sold,
            r.dom_median, r.dom_p25, r.pct_of_orig_list,
            r.expired_n, r.expiry_rate, r.top_city,
            r.n_RE, r.n_LD, r.n_MF, r.n_CM, r.n_FM, r.n_RN
        FROM r
        LEFT JOIN _agents a ON CAST(a.U_AgentID AS VARCHAR) = r.grp
        LEFT JOIN _offices o ON CAST(o.O_OfficeID AS VARCHAR) = CAST(a.U_HiddenOrgID AS VARCHAR)
        ORDER BY r.dollar_volume DESC
        """
    else:
        sql = base_sql
    out_path.parent.mkdir(parents=True, exist_ok=True)
    con.sql(f"COPY ({sql}) TO '{out_path.as_posix()}' WITH (FORMAT CSV, HEADER)")
    return con.execute(f"SELECT count(*) FROM read_csv_auto('{out_path.as_posix()}')").fetchone()[0]

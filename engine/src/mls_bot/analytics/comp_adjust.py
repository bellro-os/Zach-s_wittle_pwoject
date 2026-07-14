"""Comp-adjustment engine — adjust comparable sale prices to fit a subject.

Standard appraiser-style line-item adjustments. For each comp:

    adjusted_price = sold_price
                   + (subject_sqft - comp_sqft) * $/sqft_for_cohort
                   + (subject_age  - comp_age)  * age_premium_per_year
                   + (subject_acres - comp_acres) * land_value_per_acre

The cohort dollar coefficients are derived empirically:

  $/sqft        — median (sold_price / sqft) over recent same-city + same-class sales
  age_premium   — sign-flipped: newer == higher price; estimated as
                  ($/sqft * sqft_avg) * 0.4% per year of age difference (conservative)
  land/acre     — median (sold_price - bldg_value) / acres for sales w/ assessed_bldg

Returns a comp grid suitable for embedding in CMA reports.
"""

from __future__ import annotations

from datetime import date, timedelta

from .db import connect


def _cohort_coefficients(con, city: str, cls: str = "RE_1") -> dict[str, float]:
    """Empirically estimate adjustment dollar values for a city × class cohort."""
    city_safe = city.upper().replace("'", "''")
    cls_safe = cls.replace("'", "''")
    cutoff = (date.today() - timedelta(days=365 * 3)).isoformat()
    r = con.execute(f"""
        SELECT
            MEDIAN(TRY_CAST(sold_price AS DOUBLE) / NULLIF(TRY_CAST(sqft AS DOUBLE), 0)) AS price_per_sqft,
            MEDIAN(TRY_CAST(sqft AS DOUBLE)) AS median_sqft,
            MEDIAN(TRY_CAST(sold_price AS DOUBLE)) AS median_sold,
            MEDIAN(TRY_CAST(sold_price AS DOUBLE) / NULLIF(TRY_CAST(acres AS DOUBLE), 0)) AS price_per_acre
        FROM listings
        WHERE _class='{cls_safe}'
          AND UPPER(city)='{city_safe}'
          AND status_category='Closed'
          AND TRY_CAST(close_date AS DATE) >= '{cutoff}'
          AND TRY_CAST(sold_price AS DOUBLE) > 0
          AND TRY_CAST(sqft AS DOUBLE) > 0
    """).fetchone()
    psf, med_sqft, med_sold, ppa = r or (None, None, None, None)
    psf = float(psf) if psf else 200.0
    med_sqft = float(med_sqft) if med_sqft else 1500.0
    med_sold = float(med_sold) if med_sold else psf * med_sqft
    ppa = float(ppa) if ppa and float(ppa) > 0 else 50_000.0
    # age premium: ~0.4% of median sold price per year of age difference (newer=worth more)
    age_premium = med_sold * 0.004
    return {
        "price_per_sqft": round(psf, 2),
        "age_premium_per_year": round(age_premium, 0),
        "land_value_per_acre": round(ppa, 0),
        "median_sqft": round(med_sqft, 0),
        "median_sold": round(med_sold, 0),
    }


def adjust_comps(subject: dict, comps: list[dict], *, max_adjustment_pct: float = 0.20) -> list[dict]:
    """Adjust each comp's sold price toward the subject. Caps total adjustment
    at `max_adjustment_pct` of the comp sold price (avoids wild swings on
    radically-different comps)."""
    con = connect()
    coef = _cohort_coefficients(con,
                                  city=(subject.get("city") or "").upper().strip(),
                                  cls=subject.get("_class") or "RE_1")
    psf = coef["price_per_sqft"]
    age_p = coef["age_premium_per_year"]
    land_p = coef["land_value_per_acre"]

    s_sqft = float(subject.get("sqft") or 0)
    s_yb = float(subject.get("year_built") or 0)
    s_acres = float(subject.get("acres") or 0)

    out = []
    for c in comps:
        c_sqft = float(c.get("sqft") or 0)
        c_yb = float(c.get("year_built") or 0)
        c_acres = float(c.get("acres") or 0)
        sold = float(c.get("sold_price") or 0)
        if sold <= 0:
            continue
        adj_sqft = (s_sqft - c_sqft) * psf if (s_sqft and c_sqft) else 0
        # Newer-is-better: subject's age-at-sale would be (today - year_built);
        # comp's age-at-sale similar. Adjustment magnitude scales with |year diff|.
        adj_age = (s_yb - c_yb) * age_p if (s_yb and c_yb) else 0
        adj_acres = (s_acres - c_acres) * land_p if (s_acres and c_acres) else 0
        gross = adj_sqft + adj_age + adj_acres
        # Cap at max_adjustment_pct of sold
        cap = sold * max_adjustment_pct
        capped = max(-cap, min(cap, gross))
        adjusted = sold + capped
        out.append({
            **c,
            "adj_sqft": round(adj_sqft, 0),
            "adj_age": round(adj_age, 0),
            "adj_acres": round(adj_acres, 0),
            "adj_total_uncapped": round(gross, 0),
            "adj_total_applied": round(capped, 0),
            "adj_capped": abs(gross) > cap,
            "adjusted_sold_price": round(adjusted, 0),
        })
    out.sort(key=lambda c: abs(float(c.get("adj_total_applied") or 0)))
    return out


def cohort_coefficients_for(city: str, cls: str = "RE_1") -> dict[str, float]:
    con = connect()
    return _cohort_coefficients(con, city=city, cls=cls)

"""High-equity absentee owner flagger.

Signals we combine:
  1. Owner's mailing address does not match the property's site address.
     Normalization is intentionally crude (upper + strip + collapse spaces);
     Virginia county data is not USPS-clean and over-normalizing drops real
     matches. Adjust _norm() if you see too many false positives.
  2. Tenure: time since last recorded sale >= ABSENTEE_MIN_TENURE_YEARS.
  3. Equity proxy: since we don't have mortgage data (would need a paid
     aggregator or deed-of-trust scrape of Circuit Court), we approximate
     "likely high equity" as  last_sale_price / assessed_total <= (1 - min_equity_ratio).
     Rationale: if the owner paid $X a long time ago and the place is now
     worth much more, they have paid down a significant share and likely
     have substantial equity even if we don't know the exact balance.
     This WILL misclassify some cash-out-refinanced owners. Real mortgage
     balance requires a deed-of-trust / lien scrape — punt to phase 2.

Lead score: 0-100, tuned so fully-absentee + long tenure + big assessment
uplift ranks highest.
"""

from __future__ import annotations

import json
import re
from datetime import date

from ..config import load
from ..db import connect


def _norm(s: str | None) -> str:
    if not s:
        return ""
    s = re.sub(r"\s+", " ", s.strip().upper())
    return s


DETECT_SQL = """
SELECT parcel_id,
       owner1,
       owner2,
       site_addr1,
       site_addr2,
       mail_addr1,
       mail_addr2,
       assessed_total,
       last_sale_date,
       last_sale_price,
       acres,
       year_built,
       bedrooms,
       full_baths,
       sfla,
       zoning
FROM properties
WHERE jurisdiction = %s
  AND mail_addr1 IS NOT NULL AND mail_addr1 <> ''
  AND site_addr1 IS NOT NULL AND site_addr1 <> ''
  AND assessed_total IS NOT NULL AND assessed_total > 0
  AND last_sale_date IS NOT NULL
  AND (current_date - last_sale_date) / 365 >= %s;
"""

INSERT_SQL = """
INSERT INTO leads (category, parcel_id, listing_id, score, detail)
VALUES ('ABSENTEE_HIGH_EQUITY', %(parcel_id)s, NULL, %(score)s, %(detail)s::jsonb)
ON CONFLICT (category, coalesce(parcel_id,''), coalesce(listing_id,'')) DO UPDATE
  SET score = EXCLUDED.score, detail = EXCLUDED.detail, last_seen_at = now();
"""


def _score(tenure_years: int, equity_ratio: float) -> int:
    # tenure component: 0..40
    t = min(tenure_years, 40)
    # equity component: 0..60 (equity_ratio of 1.0 -> full 60 points)
    e = max(0.0, min(equity_ratio, 1.0)) * 60
    return int(t + e)


def detect() -> int:
    s = load()
    n = 0
    with connect() as conn, conn.cursor() as cur:
        cur.execute(DETECT_SQL, (s.assessor_jurisdiction, s.absentee_min_tenure_years))
        rows = cur.fetchall()
        today = date.today()
        for r in rows:
            site = _norm(r["site_addr1"])
            mail = _norm(r["mail_addr1"])
            if site == mail:
                continue  # owner-occupied

            assessed = float(r["assessed_total"])
            last_price = float(r["last_sale_price"]) if r["last_sale_price"] else None
            if not last_price or last_price <= 0:
                # no sale price recorded — can't estimate equity; skip
                continue

            ratio = 1 - (last_price / assessed) if assessed > last_price else 0.0
            if ratio < s.absentee_min_equity_ratio:
                continue

            tenure = (today - r["last_sale_date"]).days // 365
            score = _score(tenure, ratio)

            detail = {
                "owner1": r["owner1"],
                "owner2": r["owner2"],
                "site_addr": " ".join(x for x in [r["site_addr1"], r["site_addr2"]] if x),
                "mail_addr": " ".join(x for x in [r["mail_addr1"], r["mail_addr2"]] if x),
                "assessed_total": assessed,
                "last_sale_date": r["last_sale_date"].isoformat(),
                "last_sale_price": last_price,
                "tenure_years": tenure,
                "equity_ratio": round(ratio, 3),
                "acres": float(r["acres"]) if r["acres"] else None,
                "year_built": r["year_built"],
                "bedrooms": r["bedrooms"],
                "sfla": r["sfla"],
                "zoning": r["zoning"],
            }
            cur.execute(INSERT_SQL, {
                "parcel_id": r["parcel_id"],
                "score": score,
                "detail": json.dumps(detail),
            })
            n += 1
        conn.commit()
    return n

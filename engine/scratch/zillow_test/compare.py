"""HEAD-TO-HEAD comp engine harness: MLS-only pool vs Zillow-only pool.

For each subject address:
  1. Resolve the SUBJECT normally (same for both runs) via property_lookup.resolve_subject.
  2. Run pick_comps + _estimate_value TWICE:
       - MLS run: production pool, engine runs EXACTLY as in prod (no patching).
       - Zillow run: monkeypatch ONLY cma_compset._fast_listings_connection so the
         candidate source is a fresh DuckDB conn with the ISOLATED Zillow parquet
         registered as the `listings` view. The patch is installed/removed inside
         this test script and never touches production code or data.

Nothing is unioned: each run sees exactly one pool.

Run from C:/Users/zach/Desktop/MLS Bot:
    python scratch/zillow_test/compare.py
"""
from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path

# Mirror the engine runners' sys.path setup.
ROOT = Path("C:/Users/zach/Desktop/MLS Bot")
for p in (ROOT / "src", ROOT / "scripts"):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)
os.chdir(ROOT)  # so data/mls_lookup.parquet relative path resolves like prod

import duckdb  # noqa: E402

from mls_bot.analytics import cma_compset  # noqa: E402
from mls_bot.analytics.cma_compset import pick_comps  # noqa: E402
from mls_bot.analytics.property_lookup import resolve_subject  # noqa: E402

# build_cma exposes _estimate_value, _confidence, _num, prepare_comps.
import build_cma  # noqa: E402

ZILLOW_PARQUET = (ROOT / "scratch" / "zillow_test" / "zillow_listings.parquet").as_posix()

# AI hygiene OFF for a clean deterministic, reproducible head-to-head.
AI_HYGIENE = False


@contextmanager
def zillow_pool():
    """Temporarily swap the engine's candidate source to the Zillow parquet.

    Patches ONLY the in-memory function reference in this process. Restored on
    exit, so the very next (MLS) call sees production behavior again."""
    orig = cma_compset._fast_listings_connection

    def _zillow_conn():
        con = duckdb.connect(":memory:")
        con.execute(
            f"CREATE VIEW listings AS "
            f"SELECT * FROM read_parquet('{ZILLOW_PARQUET}')"
        )
        return con

    cma_compset._fast_listings_connection = _zillow_conn
    try:
        yield
    finally:
        cma_compset._fast_listings_connection = orig


def _haversine(lat1, lon1, lat2, lon2):
    from math import radians, sin, cos, asin, sqrt
    if None in (lat1, lon1, lat2, lon2):
        return None
    try:
        lat1, lon1, lat2, lon2 = map(float, (lat1, lon1, lat2, lon2))
    except (TypeError, ValueError):
        return None
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 3958.7613 * 2 * asin(sqrt(a))


def _run_one(subject: dict, label: str):
    """Pick comps + estimate value against whatever pool is currently active."""
    # Exclude the subject's OWN address so the Zillow pool (which contains the
    # subject's own sold row when the subject was sourced from Zillow) can't
    # comp the property against itself. Match the prod self-exclusion intent.
    self_addr = (subject.get("address") or "").split(",")[0].strip()
    excluded = [self_addr] if self_addr else None
    comps = build_cma.prepare_comps(
        subject, n_comps=6, months_back=24, ai_hygiene=AI_HYGIENE,
        excluded_comps=excluded,
    )
    if not comps:
        return {"label": label, "comps": [], "valuation": None, "confidence": None}
    val = build_cma._estimate_value(subject, comps)
    conf = build_cma._confidence(subject, comps, val)
    s_lat = build_cma._num(subject.get("latitude"))
    s_lng = build_cma._num(subject.get("longitude"))
    rows = []
    for c in comps:
        sp = build_cma._num(c.get("sold_price")) or build_cma._num(c.get("list_price"))
        sf = build_cma._num(c.get("sqft"))
        dist = c.get("_distance_mi")
        if dist is None:
            dist = _haversine(s_lat, s_lng, c.get("latitude"), c.get("longitude"))
        rows.append({
            "address": (c.get("address") or "")[:46],
            "dist_mi": round(dist, 2) if dist is not None else None,
            "sold_price": int(sp) if sp else None,
            "psf": int(round(sp / sf)) if (sp and sf and sf > 0) else None,
            "close_date": str(c.get("close_date") or "")[:10],
        })
    return {"label": label, "comps": rows, "valuation": val, "confidence": conf}


def _subject_from_zillow(address: str):
    """Build a subject dict from the Zillow parquet row matching `address`.

    Used ONLY when resolve_subject can't find the address in MLS/parcel data
    (off-MLS metro homes). The SAME subject is then run against BOTH pools, so
    the head-to-head stays apples-to-apples — only the comp source differs.
    The subject's identity/attributes come from Zillow, not from the Zillow
    comp pool, so this does not union Zillow into the MLS run's candidates.
    """
    con = duckdb.connect()
    key = address.split(",")[0].strip().upper()
    row = con.execute(
        f"SELECT * FROM read_parquet('{ZILLOW_PARQUET}') "
        f"WHERE UPPER(address) LIKE '{key}%' ORDER BY close_date DESC LIMIT 1"
    ).fetchdf()
    if row.empty:
        return None
    r = row.iloc[0].to_dict()
    return {
        "address": r.get("address"),
        "city": r.get("city"),
        "county": r.get("county"),
        "_class": "RE_1",
        "sqft": float(r["sqft"]) if r.get("sqft") else None,
        "acres": float(r["acres"]) if r.get("acres") else None,
        "bedrooms": float(r["bedrooms"]) if r.get("bedrooms") else None,
        "full_baths": float(r["full_baths"]) if r.get("full_baths") else None,
        "half_baths": None,
        "year_built": None,
        "latitude": float(r["latitude"]) if r.get("latitude") else None,
        "longitude": float(r["longitude"]) if r.get("longitude") else None,
        "list_price": None,
        "parcel_id": "",        # blank so it can't self-exclude a real comp wrongly
        "subdivision": "",
        "high_school": "",
    }


def run_subject(address: str):
    print("\n" + "=" * 100)
    print(f"SUBJECT: {address}")
    print("=" * 100)
    subject = resolve_subject(address=address)
    subj_src = "MLS/parcel"
    # If MLS/parcel resolution missed (returned nothing) OR returned a junk
    # land hit with no coordinates (off-MLS metro address fuzzily matched to a
    # statewide parcel), fall back to the Zillow-row subject so BOTH pools get
    # the SAME, correct subject.
    bad_resolve = (not subject) or (
        build_cma._num((subject or {}).get("latitude")) is None
        and build_cma._num((subject or {}).get("longitude")) is None
    )
    if bad_resolve:
        zsubj = _subject_from_zillow(address)
        if zsubj:
            subject = zsubj
            subj_src = "Zillow-row (off-MLS subject)"
        elif not subject:
            print("  !! Could not resolve subject — SKIPPING")
            return None
    for key in ("sqft", "acres", "list_price", "original_list_price", "sold_price",
                "bedrooms", "full_baths", "half_baths", "year_built",
                "latitude", "longitude"):
        v = build_cma._num(subject.get(key))
        if v is not None:
            subject[key] = v
    print(f"  subject_source={subj_src}")
    print(f"  resolved: city={subject.get('city')!r} county={subject.get('county')!r} "
          f"class={subject.get('_class')!r} sqft={subject.get('sqft')} "
          f"beds={subject.get('bedrooms')} baths={subject.get('full_baths')} "
          f"acres={subject.get('acres')} lat={subject.get('latitude')} lng={subject.get('longitude')}")

    # MLS run — production pool, NO patching.
    mls = _run_one(dict(subject), "MLS")
    # Zillow run — isolated pool via context-managed monkeypatch.
    with zillow_pool():
        zil = _run_one(dict(subject), "ZILLOW")

    for r in (mls, zil):
        print(f"\n  --- {r['label']} POOL ---")
        if not r["comps"]:
            print("    (no comps)")
            continue
        print(f"    comp_count={len(r['comps'])}")
        print(f"    {'address':46} {'dist':>6} {'sold':>10} {'$/sf':>6} {'close':>11}")
        for c in r["comps"]:
            print(f"    {c['address']:46} {str(c['dist_mi']):>6} "
                  f"{str(c['sold_price']):>10} {str(c['psf']):>6} {c['close_date']:>11}")
        v = r["valuation"]
        tier = r["confidence"][0] if r["confidence"] else "?"
        print(f"    VALUATION  low=${v.low:,}  mid=${v.mid:,}  high=${v.high:,}  "
              f"$psf={v.ppsf:.0f}  conf={tier}  div={v.divergence_pct:.0f}%")

    # Agreement summary
    summary = {"address": address}
    if mls["valuation"] and zil["valuation"]:
        m, z = mls["valuation"].mid, zil["valuation"].mid
        pct = (z - m) / m * 100 if m else None
        # Normalize addresses to street-number + first street word so the
        # MLS form ("504 JEFFERSON Street") and Zillow form ("504 Jefferson
        # St, Blacksburg, VA 24060") compare equal — otherwise overlap is a
        # formatting false-zero.
        import re as _re

        def _akey(a):
            head = a.split(",")[0].upper()
            toks = _re.findall(r"[A-Z0-9]+", head)
            # number + first 1-2 name tokens (drop suffix like ST/STREET/DR)
            return " ".join(toks[:3]) if toks else head
        mls_addrs = {_akey(c["address"]) for c in mls["comps"]}
        zil_addrs = {_akey(c["address"]) for c in zil["comps"]}
        overlap = mls_addrs & zil_addrs
        print(f"\n  >> AGREEMENT: MLS mid=${m:,}  ZILLOW mid=${z:,}  "
              f"diff={pct:+.1f}%  comp_overlap={len(overlap)}")
        summary.update(mls_mid=m, zil_mid=z, diff_pct=pct,
                       mls_n=len(mls["comps"]), zil_n=len(zil["comps"]),
                       overlap=len(overlap))
    else:
        print(f"\n  >> One side has NO valuation: "
              f"MLS={'ok' if mls['valuation'] else 'NONE'} "
              f"ZILLOW={'ok' if zil['valuation'] else 'NONE'}")
        summary.update(mls_mid=mls["valuation"].mid if mls["valuation"] else None,
                       zil_mid=zil["valuation"].mid if zil["valuation"] else None,
                       diff_pct=None,
                       mls_n=len(mls["comps"]), zil_n=len(zil["comps"]), overlap=0)
    return summary


DENSE_BOTH = [
    "509 Jefferson St, Blacksburg, VA",
    "845 JEFFERSON Circle, Christiansburg, VA",
    "1410 SHERWOOD Drive, Christiansburg, VA",
    "1701 TRILLIUM Lane, Blacksburg, VA",
]
THIN_OR_RICH = [
    "6021 Strawberry Ct, Wise, VA",
    "4040 Poplar St, Fairfax, VA 22030",
    "1805 Rich Ct, Virginia Beach, VA 23464",
    "6717 Dawnwood Rd, Roanoke, VA 24018",
]


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    addrs = []
    if which in ("all", "dense"):
        addrs += DENSE_BOTH
    if which in ("all", "thin"):
        addrs += THIN_OR_RICH
    if which not in ("all", "dense", "thin"):
        addrs = [which]

    results = []
    for a in addrs:
        try:
            r = run_subject(a)
            if r:
                results.append(r)
        except Exception as e:
            import traceback
            print(f"\n  !! ERROR on {a}: {e}")
            traceback.print_exc()

    print("\n\n" + "#" * 100)
    print("HEAD-TO-HEAD SUMMARY (MLS mid vs ZILLOW mid)")
    print("#" * 100)
    print(f"{'address':44} {'MLS mid':>12} {'ZIL mid':>12} {'diff%':>8} "
          f"{'MLS n':>6} {'ZIL n':>6} {'ovlp':>5}")
    for r in results:
        m = f"${r['mls_mid']:,}" if r.get("mls_mid") else "NONE"
        z = f"${r['zil_mid']:,}" if r.get("zil_mid") else "NONE"
        d = f"{r['diff_pct']:+.1f}%" if r.get("diff_pct") is not None else "-"
        print(f"{r['address'][:44]:44} {m:>12} {z:>12} {d:>8} "
              f"{str(r.get('mls_n','-')):>6} {str(r.get('zil_n','-')):>6} {str(r.get('overlap','-')):>5}")


if __name__ == "__main__":
    main()

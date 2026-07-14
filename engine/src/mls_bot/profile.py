"""Read a parcel JSONL dump and print a profile — no DB required.

    python tasks.py profile data/blacksburg_parcels.jsonl
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path


ENTITY_PATTERNS = [
    r"\bLLC\b", r"\bL\.?L\.?C\.?\b", r"\bINC\b", r"\bCORP\b", r"\bCORPORATION\b",
    r"\bTRUST\b", r"\bTRUSTEE", r"\bTR\s*$", r"FAMILY\s+TR\b",
    r"\bLP\b", r"\bLLP\b", r"\bLTD\b", r"\bLIMITED\b",
    r"\bPARTNERSHIP\b", r"\bHOLDINGS?\b", r"\bPROPERTIES\b", r"\bASSOCIATES\b",
    r"\bGROUP\b", r"\bINVESTMENTS?\b", r"\bCHURCH\b", r"\bFOUNDATION\b",
    r"\bREAL ESTATE\b", r"\bRENTALS?\b", r"\bDEVELOPMENT\b", r"\bDEVELOPERS\b",
    r"\bHOMES\b", r"\bCONSTRUCTION\b", r"\bCAPITAL\b", r"\bVENTURES\b",
]
GOVT_PATTERNS = [
    r"COMMONWEALTH OF", r"\bUSA\b", r"UNITED STATES", r"U\.?\s?S\.?\s+GOVERNMENT",
    r"\bSTATE OF\b", r"\bCOUNTY OF\b", r"COUNTY BOARD", r"\bTOWN OF\b", r"\bCITY OF\b",
    r"\bMONTGOMERY COUNTY\b", r"DEPT OF", r"DEPARTMENT OF", r"\bVA DEPT\b",
    r"BOARD OF SUPERVISORS", r"SCHOOL BOARD", r"HOUSING AUTHORITY",
    r"HOUSING PARTNERS", r"\bAUTHORITY\b",
    r"VIRGINIA POLYTECHNIC", r"VIRGINIA TECH", r"\bVPI\b", r"\bUNIVERSITY\b",
    # HOAs / condo associations / subdivision common areas
    r"\bHOA\b", r"HOME\s*OWNERS?", r"HOMEOWNERS?\s+ASSOC",
    r"\bCONDOMINIUMS?\b", r"\bCONDO\s+ASSOC",
    r"\bSUBDIVISION\b", r"\bTOWNHOMES?\s+HOMEOWNERS?",
    r"VILLAGE\s+AT\b", r"VILLAS\s+AT\b", r"COMMONS\s+AT\b",
    # Cemeteries and similar non-owner markers the county uses
    r"\bCEMETERY\b", r"\bCEMETARY\b",
    # Student / religious / nonprofit institutions
    r"\bHILLEL\b", r"\bFRATERNITY\b", r"\bSORORITY\b",
    r"ALUMNI\s+ASSOC", r"\bFELLOWSHIP\b", r"HABITAT\s+FOR\b",
    r"\bSYNAGOGUE\b", r"\bTEMPLE\s+OF\b", r"\bMINISTRIES\b", r"\bMINISTRY\b",
]

_ENTITY_RE = re.compile("|".join(ENTITY_PATTERNS))
_GOVT_RE = re.compile("|".join(GOVT_PATTERNS))


def classify_owner(owner1: str | None) -> str:
    if not owner1:
        return "unknown"
    u = owner1.upper()
    if _GOVT_RE.search(u):
        return "govt_or_institution"
    if _ENTITY_RE.search(u):
        return "entity"
    return "person"


def _norm_addr(s: str | None) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", s.strip().upper())


_SUFFIX_MAP = {
    "STREET": "ST", "AVENUE": "AVE", "DRIVE": "DR", "ROAD": "RD",
    "LANE": "LN", "COURT": "CT", "BOULEVARD": "BLVD", "HIGHWAY": "HWY",
    "CIRCLE": "CIR", "PLACE": "PL", "PARKWAY": "PKWY", "TERRACE": "TER",
    "TRAIL": "TRL", "EXPRESSWAY": "EXPY", "SQUARE": "SQ", "MOUNT": "MT",
    "POBOX": "PO BOX", "P.O.": "PO", "P O": "PO",
    "APARTMENT": "APT", "SUITE": "STE", "NUMBER": "",
}


def _norm_mail(addr1: str | None, addr2: str | None) -> str:
    """Normalize a (street, city/state/zip) mailing address for clustering.

    Combines both lines, uppercases, strips punctuation, collapses whitespace,
    and maps common suffix words to their USPS abbreviations. Conservative on
    purpose -- the goal is to merge 'JOHN SMITH' and 'J SMITH LLC' at the same
    mailbox, not to force-merge near-neighbors.
    """
    parts: list[str] = []
    for s in (addr1, addr2):
        if s:
            t = s.strip().upper()
            t = re.sub(r"[.,#]", " ", t)
            t = re.sub(r"\s+", " ", t).strip()
            if t:
                parts.append(t)
    if not parts:
        return ""
    tokens = " ".join(parts).split()
    out: list[str] = []
    for tok in tokens:
        repl = _SUFFIX_MAP.get(tok, tok)
        if repl:
            out.append(repl)
    # Trim trailing ZIP+4 suffix (keep the 5-digit zip for disambiguation)
    return re.sub(r"-\d{4}\b", "", " ".join(out))


def _bucket(n: float, step: int) -> str:
    b = int(n // step) * step
    return f"{b:,}-{b + step - 1:,}"


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def profile(jsonl_path: str) -> dict:
    p = Path(jsonl_path)
    if not p.exists():
        raise FileNotFoundError(jsonl_path)

    rows: list[dict] = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))

    today = date.today()
    owner_types = Counter()
    sale_decade = Counter()
    assessed_bucket = Counter()
    tenure_bucket = Counter()
    absentee = Counter()
    top_owners = Counter()

    # Filter-threshold matrix
    filter_counts: dict[tuple[int, int], int] = {}
    thresholds = [
        (5, 40), (5, 60),
        (10, 40), (10, 60), (10, 80),
        (20, 40), (20, 60),
    ]
    for t in thresholds:
        filter_counts[t] = 0

    sample_leads: list[dict] = []

    for r in rows:
        otype = classify_owner(r.get("owner1"))
        owner_types[otype] += 1
        if r.get("owner1"):
            top_owners[r["owner1"]] += 1

        site = _norm_addr(r.get("site_addr1"))
        mail = _norm_addr(r.get("mail_addr1"))
        if not site:
            abs_status = "no_site_addr"
        elif not mail:
            abs_status = "no_mail_addr"
        elif site == mail:
            abs_status = "owner_occupied"
        else:
            abs_status = "absentee"
        absentee[abs_status] += 1

        sd = _parse_date(r.get("last_sale_date"))
        if sd:
            sale_decade[(sd.year // 10) * 10] += 1
            tenure = (today - sd).days // 365
            tenure_bucket[min(tenure // 5 * 5, 50)] += 1
        else:
            sale_decade[None] += 1

        at = r.get("assessed_total")
        if at:
            assessed_bucket[_bucket(float(at), 100_000)] += 1

        # Compute how each row fares against each (tenure, equity%) threshold
        last_price = r.get("last_sale_price")
        if (abs_status == "absentee" and sd and at and last_price
                and float(last_price) > 0 and float(at) > float(last_price)
                and otype == "person"):
            tenure_y = (today - sd).days // 365
            eq_pct = (1 - float(last_price) / float(at)) * 100
            for (min_t, min_eq) in thresholds:
                if tenure_y >= min_t and eq_pct >= min_eq:
                    filter_counts[(min_t, min_eq)] += 1
            if tenure_y >= 10 and eq_pct >= 60:
                sample_leads.append({
                    "parcel_id": r.get("parcel_id"),
                    "owner1": r.get("owner1"),
                    "site": r.get("site_addr1"),
                    "mail": r.get("mail_addr1"),
                    "assessed": float(at),
                    "bought": r.get("last_sale_date"),
                    "bought_for": float(last_price),
                    "tenure": tenure_y,
                    "equity_pct": round(eq_pct, 1),
                })

    sample_leads.sort(key=lambda x: (x["tenure"], x["equity_pct"]), reverse=True)

    return {
        "total": len(rows),
        "owner_types": dict(owner_types),
        "absentee_breakdown": dict(absentee),
        "sale_decade": {str(k) if k else "no_sale": v for k, v in sorted(sale_decade.items(), key=lambda kv: (kv[0] is None, kv[0]))},
        "assessed_bucket_top": dict(assessed_bucket.most_common(10)),
        "tenure_bucket": {f"{k}-{k+4}y": v for k, v in sorted(tenure_bucket.items())},
        "top_owners": dict(top_owners.most_common(15)),
        "absentee_person_filter_counts": {f"tenure>={t}y & equity>={e}%": c
                                          for (t, e), c in filter_counts.items()},
        "sample_leads_top10": sample_leads[:10],
    }


def print_profile(jsonl_path: str) -> None:
    p = profile(jsonl_path)
    print(f"\n=== parcels: {p['total']:,} ===\n")

    print("owner types:")
    for k, v in p["owner_types"].items():
        print(f"  {k:22s} {v:>6,}  ({v/p['total']*100:5.1f}%)")

    print("\nabsentee breakdown:")
    for k, v in p["absentee_breakdown"].items():
        print(f"  {k:22s} {v:>6,}  ({v/p['total']*100:5.1f}%)")

    print("\nsale decade:")
    for k, v in p["sale_decade"].items():
        print(f"  {k:>10s}  {v:>6,}")

    print("\ntop 15 owners (repeated ownership = landlord or institution):")
    for k, v in p["top_owners"].items():
        print(f"  {v:>4,}  {k}")

    print("\nassessed value buckets (top 10, in USD):")
    for k, v in p["assessed_bucket_top"].items():
        print(f"  ${k}: {v:>6,}")

    print("\ntenure buckets (years since last sale):")
    for k, v in p["tenure_bucket"].items():
        print(f"  {k:10s} {v:>6,}")

    print("\nabsentee PERSON lead counts at various filter thresholds:")
    for k, v in p["absentee_person_filter_counts"].items():
        print(f"  {k:30s} {v:>6,}")

    print("\ntop 10 candidate leads (person, absentee, tenure>=10y, equity>=60%):")
    for s in p["sample_leads_top10"]:
        print(f"  [{s['tenure']}y, eq {s['equity_pct']}%] {s['owner1']}")
        print(f"      site:  {s['site']}")
        print(f"      mail:  {s['mail']}")
        print(f"      assessed ${s['assessed']:,.0f}  |  bought {s['bought']} for ${s['bought_for']:,.0f}")


def _load_rows(jsonl_path: str) -> list[dict]:
    p = Path(jsonl_path)
    if not p.exists():
        raise FileNotFoundError(jsonl_path)
    out: list[dict] = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                out.append(json.loads(line))
    return out


def top_owners(jsonl_path: str, owner_type: str = "person", limit: int = 25) -> list[dict]:
    """Rank owners by number of Blacksburg parcels.

    owner_type: 'person', 'entity', 'govt_or_institution', or 'all'.
    """
    rows = _load_rows(jsonl_path)
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        o = r.get("owner1")
        if not o:
            continue
        if owner_type != "all" and classify_owner(o) != owner_type:
            continue
        groups[o].append(r)

    results: list[dict] = []
    for owner, parcels in groups.items():
        total_val = sum(float(p.get("assessed_total") or 0) for p in parcels)
        owner_occupied = 0
        absentee_ct = 0
        mail_addrs: Counter = Counter()
        sites: list[str] = []
        most_recent_sale: date | None = None

        for p in parcels:
            site = _norm_addr(p.get("site_addr1"))
            mail = _norm_addr(p.get("mail_addr1"))
            if site and mail:
                if site == mail:
                    owner_occupied += 1
                else:
                    absentee_ct += 1
            if p.get("mail_addr1"):
                mail_addrs[(p.get("mail_addr1") or "").strip() + " | " + (p.get("mail_addr2") or "").strip()] += 1
            if p.get("site_addr1"):
                sites.append((p.get("site_addr1") or "").strip())
            sd = _parse_date(p.get("last_sale_date"))
            if sd and (most_recent_sale is None or sd > most_recent_sale):
                most_recent_sale = sd

        results.append({
            "owner": owner,
            "count": len(parcels),
            "total_assessed": total_val,
            "owner_occupied": owner_occupied,
            "absentee": absentee_ct,
            "primary_mail_addr": mail_addrs.most_common(1)[0][0] if mail_addrs else None,
            "sample_sites": sites[:5],
            "last_acquired": most_recent_sale.isoformat() if most_recent_sale else None,
        })

    results.sort(key=lambda x: (x["count"], x["total_assessed"]), reverse=True)
    return results[:limit]


def top_by_mail(jsonl_path: str, limit: int = 30, exclude_govt: bool = True) -> list[dict]:
    """Rank parcel portfolios by shared mailing address.

    Same mail = same owner (user rule). Captures a landlord who files parcels
    under multiple name variants or under both personal and LLC names.
    """
    rows = _load_rows(jsonl_path)
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        key = _norm_mail(r.get("mail_addr1"), r.get("mail_addr2"))
        if not key:
            continue
        if exclude_govt:
            o = (r.get("owner1") or "").upper()
            if _GOVT_RE.search(o):
                continue
        groups[key].append(r)

    results: list[dict] = []
    for mail_key, parcels in groups.items():
        names: Counter = Counter()
        types: Counter = Counter()
        total_val = 0.0
        owner_occ = 0
        absentee_ct = 0
        sites: list[str] = []
        most_recent_sale: date | None = None
        for p in parcels:
            o = p.get("owner1")
            if o:
                names[o] += 1
                types[classify_owner(o)] += 1
            total_val += float(p.get("assessed_total") or 0)
            site = _norm_addr(p.get("site_addr1"))
            mail = _norm_addr(p.get("mail_addr1"))
            if site and mail:
                if site == mail:
                    owner_occ += 1
                else:
                    absentee_ct += 1
            if p.get("site_addr1"):
                sites.append((p.get("site_addr1") or "").strip())
            sd = _parse_date(p.get("last_sale_date"))
            if sd and (most_recent_sale is None or sd > most_recent_sale):
                most_recent_sale = sd

        results.append({
            "mail_key": mail_key,
            "count": len(parcels),
            "total_assessed": total_val,
            "owner_occupied": owner_occ,
            "absentee": absentee_ct,
            "distinct_owner_names": len(names),
            "top_names": names.most_common(4),
            "types": dict(types),
            "sample_sites": sites[:5],
            "last_acquired": most_recent_sale.isoformat() if most_recent_sale else None,
        })

    results.sort(key=lambda x: (x["count"], x["total_assessed"]), reverse=True)
    return results[:limit]


_BAD_MAIL_KEYS = {"COMMON AREA", "COMMON AREAS", "SAME", "SAME AS ABOVE", "UNKNOWN"}


def new_investors(
    jsonl_path: str,
    recency_years: int = 3,
    min_count: int = 2,
    min_distinct_sites: int = 2,
    min_distinct_dates: int = 1,
    group_by: str = "mail",
    owner_type: str = "person",
    jurisdiction: str | None = None,
    limit: int = 30,
) -> list[dict]:
    """Owners who started accumulating multiple parcels in the last N years.

    Uses the most recent sale per parcel as a proxy for acquisition. An owner
    qualifies when:
      - every parcel in current holdings was acquired within recency_years
      - they hold >= min_count parcels
      - those parcels span >= min_distinct_sites distinct site addresses
      - purchases span >= min_distinct_dates distinct sale dates

    min_distinct_sites defaults to 2 to filter out multi-unit buildings where
    every unit has its own parcel_id (looks like a portfolio; isn't one).
    Set =1 if you want to include single-building multi-parcel buys.
    """
    rows = _load_rows(jsonl_path)
    today = date.today()
    cutoff = date(today.year - recency_years, today.month, today.day)

    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if jurisdiction and (r.get("jurisdiction") or "").upper() != jurisdiction.upper():
            continue
        o = r.get("owner1")
        if not o:
            continue
        if owner_type != "all" and classify_owner(o) != owner_type:
            continue
        if group_by == "mail":
            key = _norm_mail(r.get("mail_addr1"), r.get("mail_addr2"))
            if key in _BAD_MAIL_KEYS:
                continue
        else:
            key = o
        if not key:
            continue
        groups[key].append(r)

    results: list[dict] = []
    for key, parcels in groups.items():
        if len(parcels) < min_count:
            continue
        dates = [_parse_date(p.get("last_sale_date")) for p in parcels]
        if any(d is None for d in dates):
            continue
        date_values: list[date] = [d for d in dates if d is not None]
        oldest = min(date_values)
        newest = max(date_values)
        if oldest < cutoff:
            continue

        distinct_sites = len({_norm_addr(p.get("site_addr1")) for p in parcels if p.get("site_addr1")})
        distinct_dates = len({p.get("last_sale_date") for p in parcels if p.get("last_sale_date")})
        if distinct_sites < min_distinct_sites:
            continue
        if distinct_dates < min_distinct_dates:
            continue

        names: Counter = Counter()
        types: Counter = Counter()
        absentee_ct = 0
        owner_occ = 0
        total_val = 0.0
        total_paid = 0.0
        parcel_rows: list[dict] = []
        seen_txn: set[tuple] = set()

        for p in parcels:
            n = p.get("owner1")
            if n:
                names[n] += 1
                types[classify_owner(n)] += 1
            total_val += float(p.get("assessed_total") or 0)
            # Only count sale_price once per distinct transaction (date + price)
            # to avoid 10x double-counting on a 10-unit building.
            txn_key = (p.get("last_sale_date"), p.get("last_sale_price"))
            if txn_key not in seen_txn and p.get("last_sale_price"):
                total_paid += float(p.get("last_sale_price") or 0)
                seen_txn.add(txn_key)
            site = _norm_addr(p.get("site_addr1"))
            mail = _norm_addr(p.get("mail_addr1"))
            if site and mail and site == mail:
                owner_occ += 1
            elif site and mail:
                absentee_ct += 1
            parcel_rows.append({
                "parcel_id": p.get("parcel_id"),
                "sale_date": p.get("last_sale_date"),
                "sale_price": float(p.get("last_sale_price") or 0) or None,
                "assessed": float(p.get("assessed_total") or 0) or None,
                "site_addr": (p.get("site_addr1") or "").strip(),
                "bedrooms": p.get("bedrooms"),
                "sfla": p.get("sfla"),
                "zoning": p.get("zoning"),
                "jurisdiction": p.get("jurisdiction"),
            })

        parcel_rows.sort(key=lambda x: x["sale_date"] or "")

        # Mailing addresses present in the group (in case group_by="owner")
        mail_keys = Counter(_norm_mail(p.get("mail_addr1"), p.get("mail_addr2")) for p in parcels)

        results.append({
            "group_key": key,
            "group_by": group_by,
            "count": len(parcels),
            "distinct_sites": distinct_sites,
            "distinct_dates": distinct_dates,
            "total_assessed": total_val,
            "total_paid": total_paid,
            "owner_occupied": owner_occ,
            "absentee": absentee_ct,
            "oldest_acquisition": oldest.isoformat(),
            "newest_acquisition": newest.isoformat(),
            "distinct_owner_names": len(names),
            "top_names": names.most_common(3),
            "types": dict(types),
            "primary_mail": mail_keys.most_common(1)[0][0] if mail_keys else "",
            "parcels": parcel_rows,
        })

    # Rank: multiple separate transactions first (strongest investor signal),
    # then distinct sites, then total count, then recency.
    results.sort(
        key=lambda x: (x["distinct_dates"], x["distinct_sites"], x["count"], x["newest_acquisition"]),
        reverse=True,
    )
    return results[:limit]


def print_new_investors(
    jsonl_path: str,
    recency_years: int = 3,
    min_count: int = 2,
    min_distinct_sites: int = 2,
    min_distinct_dates: int = 1,
    group_by: str = "mail",
    owner_type: str = "person",
    jurisdiction: str | None = None,
    limit: int = 30,
) -> None:
    out = new_investors(
        jsonl_path,
        recency_years=recency_years,
        min_count=min_count,
        min_distinct_sites=min_distinct_sites,
        min_distinct_dates=min_distinct_dates,
        group_by=group_by,
        owner_type=owner_type,
        jurisdiction=jurisdiction,
        limit=limit,
    )
    juris_label = jurisdiction or "ALL"
    print(
        f"\n=== new {owner_type} investors in {juris_label} — "
        f"{min_count}+ parcels at {min_distinct_sites}+ addresses, "
        f"all acquired in last {recency_years}y, grouped by {group_by} ===\n"
    )
    if not out:
        print("(no matches — try raising recency_years, or lowering min_distinct_sites/min_count)")
        return
    print(f"{'#':>3}  {'cnt':>4}  {'sit':>3}  {'dt':>3}  {'abs':>3}  {'assessed $':>12}  {'paid $':>12}  "
          f"{'first buy':>10}  {'last buy':>10}  owner / mail")
    print("-" * 120)
    for i, r in enumerate(out, 1):
        label = r["group_key"]
        if r["group_by"] == "mail" and r["top_names"]:
            label = f"{r['top_names'][0][0]}  @  {r['group_key']}"
        print(f"{i:>3}  {r['count']:>4}  {r['distinct_sites']:>3}  {r['distinct_dates']:>3}  "
              f"{r['absentee']:>3}  ${r['total_assessed']:>10,.0f}  "
              f"${r['total_paid']:>10,.0f}  {r['oldest_acquisition']:>10}  "
              f"{r['newest_acquisition']:>10}  {label}")
    print()
    print("legend: cnt=parcels, sit=distinct sites, dt=distinct sale dates, abs=absentee")
    print()
    print("--- details (top 10) ---\n")
    for i, r in enumerate(out[:10], 1):
        print(f"{i}. {r['primary_mail'] or r['group_key']}")
        print(f"   names at this mailbox: " + ", ".join(f"{n} ({c})" for n, c in r["top_names"]))
        print(f"   {r['count']} parcels, assessed ${r['total_assessed']:,.0f}, "
              f"paid ${r['total_paid']:,.0f} total")
        print(f"   types: {r['types']}, absentee {r['absentee']}/{r['count']}")
        for p in r["parcels"]:
            price = f"${p['sale_price']:,.0f}" if p["sale_price"] else "$?"
            assessed = f"${p['assessed']:,.0f}" if p["assessed"] else "$?"
            print(f"     {p['sale_date']}  bought {price}  |  now {assessed}  "
                  f"|  {p['site_addr']}  ({p['jurisdiction']}, {p.get('zoning') or '?'})")
        print()


def print_top_by_mail(jsonl_path: str, limit: int = 30, exclude_govt: bool = True) -> None:
    out = top_by_mail(jsonl_path, limit=limit, exclude_govt=exclude_govt)
    print(f"\n=== top {len(out)} portfolios grouped by mailing address ===\n")
    print(f"{'#':>3}  {'cnt':>4}  {'assessed $':>13}  {'own':>3}  {'abs':>3}  {'nms':>3}  mail address")
    print("-" * 100)
    for i, r in enumerate(out, 1):
        print(f"{i:>3}  {r['count']:>4}  ${r['total_assessed']:>11,.0f}  "
              f"{r['owner_occupied']:>3}  {r['absentee']:>3}  {r['distinct_owner_names']:>3}  {r['mail_key']}")
    print()
    print("legend: cnt=parcels, own=owner-occupied, abs=absentee, nms=distinct owner-name variants at this mailbox")
    print()
    print("--- details (top 15) ---\n")
    for i, r in enumerate(out[:15], 1):
        print(f"{i}. {r['mail_key']}")
        print(f"   {r['count']} parcels, assessed ${r['total_assessed']:,.0f}, last acquired {r['last_acquired']}")
        print(f"   types: {r['types']}")
        for name, c in r["top_names"]:
            print(f"     - {c}x  {name}")
        for s in r["sample_sites"][:3]:
            print(f"     site: {s}")
        print()


def print_top_owners(jsonl_path: str, owner_type: str = "person", limit: int = 25) -> None:
    out = top_owners(jsonl_path, owner_type=owner_type, limit=limit)
    print(f"\n=== top {len(out)} {owner_type} owners in Blacksburg ===\n")
    print(f"{'#':>3}  {'cnt':>4}  {'assessed $':>13}  {'own':>3}  {'abs':>3}  owner")
    print("-" * 80)
    for i, r in enumerate(out, 1):
        print(f"{i:>3}  {r['count']:>4}  ${r['total_assessed']:>11,.0f}  "
              f"{r['owner_occupied']:>3}  {r['absentee']:>3}  {r['owner']}")
    print()
    print("legend: cnt = parcels, own = owner-occupied, abs = absentee (mailed elsewhere)")
    print()
    # Detailed view of top 10 so you can eyeball candidates
    print("--- details (top 10) ---\n")
    for i, r in enumerate(out[:10], 1):
        print(f"{i}. {r['owner']} — {r['count']} parcels, assessed ${r['total_assessed']:,.0f}")
        print(f"   mails to: {r['primary_mail_addr']}")
        print(f"   last acquired: {r['last_acquired']}")
        print(f"   sample sites: {r['sample_sites'][:3]}")
        print()

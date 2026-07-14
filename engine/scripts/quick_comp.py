"""Numbers-only CMA quick comp — no PDF, no branding.

Runs the exact production valuation path (resolve_subject -> pick_comps ->
_estimate_value) with the current logic and prints the value, range, methods,
and the comp set. Mirrors how build_cma() resolves + coerces the subject.

    python -X utf8 scripts/quick_comp.py "509 Jefferson St Blacksburg VA"
    python -X utf8 scripts/quick_comp.py "..." --n 6 --months 24
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for p in (str(_ROOT / "scripts"), str(_ROOT / "src")):
    if p in sys.path:
        sys.path.remove(p)
    sys.path.insert(0, p)
import os
os.chdir(_ROOT)

from build_cma import _resolve_subject, _estimate_value, _num, _round_to_5k  # noqa: E402
from mls_bot.analytics.cma_compset import pick_comps  # noqa: E402

_COERCE = ("sqft", "acres", "list_price", "original_list_price", "sold_price",
           "bedrooms", "full_baths", "half_baths", "year_built", "feed_dom",
           "latitude", "longitude")


def money(n):
    f = _num(n)
    return f"${int(round(f)):,}" if f is not None else "—"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("address")
    ap.add_argument("--parcel", default=None)
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--months", type=int, default=24)
    a = ap.parse_args()

    subject = _resolve_subject(address=a.address, parcel_id=a.parcel)
    if not subject:
        print(f"Could not locate subject: {a.address!r}", file=sys.stderr)
        return 1
    for k in _COERCE:
        v = _num(subject.get(k))
        if v is not None:
            subject[k] = v

    comps = pick_comps(subject, n=a.n, months_back=a.months)
    if not comps:
        print("No comps found (try a wider --months).", file=sys.stderr)
        return 1
    val = _estimate_value(subject, comps)

    sqft = _num(subject.get("sqft"))
    print("=" * 70)
    print(f"SUBJECT: {subject.get('address')}  ({subject.get('city')}, {subject.get('county')})")
    bd = subject.get("bedrooms"); ba = subject.get("full_baths")
    print(f"  {int(sqft) if sqft else '?'} sqft · {subject.get('acres','?')} ac · "
          f"{int(bd) if _num(bd) else '?'}bd/{int(ba) if _num(ba) else '?'}ba · "
          f"built {subject.get('year_built','?')}"
          + (f" · current list {money(subject.get('list_price'))}" if _num(subject.get('list_price')) else ""))
    print("=" * 70)
    # Display rounding ($5k) happens here — ValuationResult is unrounded.
    v_mid, v_low, v_high = _round_to_5k(val.mid), _round_to_5k(val.low), _round_to_5k(val.high)
    ppsf_subj = (v_mid / sqft) if (sqft and v_mid) else None
    print(f"ESTIMATED VALUE:  {money(v_mid)}")
    print(f"  range:          {money(v_low)} – {money(v_high)}")
    print(f"  comp $/sqft:    ${val.ppsf:,.0f}" + (f"   implied subject $/sqft: ${ppsf_subj:,.0f}" if ppsf_subj else ""))
    print(f"  method spread:  {val.divergence_pct:.0f}%")
    print("\nMETHODS:")
    for m in val.methods:
        print(f"  {m.name:<22} {money(m.value) if m.value else '(n/a)':>12}   {m.rationale}")

    print(f"\nCOMPARABLES ({len(comps)}):")
    print(f"  {'sold':>10}{'$/sf':>7}{'sqft':>7}{'ac':>6}{'bd/ba':>7}{'built':>7}  closed     address")
    for c in comps:
        sp = _num(c.get("sold_price")); sf = _num(c.get("sqft"))
        ppsf = (sp / sf) if (sp and sf) else 0
        cbd = _num(c.get("bedrooms")); cba = _num(c.get("full_baths"))
        print(f"  {money(sp):>10}{('$'+str(int(ppsf))) if ppsf else '—':>7}"
              f"{int(sf) if sf else '—':>7}{(c.get('acres') if c.get('acres') is not None else '—'):>6}"
              f"{(str(int(cbd)) if cbd else '?')+'/'+(str(int(cba)) if cba else '?'):>7}"
              f"{str(c.get('year_built') or '—'):>7}  {str(c.get('close_date') or '')[:10]:<10} "
              f"{str(c.get('address') or '')[:30]}")
    print("=" * 70)
    print("Deterministic estimate from the live NRV comp set — quick comp, not a "
          "rendered CMA. For client delivery, generate the branded one-pager.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

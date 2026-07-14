"""Standing CMA accuracy benchmark — a fixed set of real, known properties the
team tracks. Run after ANY CMA-engine change to spot regressions/shifts on homes
we have a feel for, alongside the statistical backtest (scripts/backtest_cma.py).

    python -X utf8 scripts/cma_benchmarks.py                # full path (AVM + hygiene) — matches the live CMA
    python -X utf8 scripts/cma_benchmarks.py --no-hygiene   # AVM off, no LLM — fast + fully reproducible
    python -X utf8 scripts/cma_benchmarks.py --json         # machine-readable
    CMA_HYGIENE_MODEL=claude-opus-4-8 python -X utf8 scripts/cma_benchmarks.py   # match the live (Opus) model

Edit BENCHMARKS to add/remove addresses. Each run prints the resolved subject,
the estimate + supported range, comp count, and the MLS-confirmed last sale (the
nearest thing to ground truth we have for an off-market home).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(_ROOT / "scripts"), str(_ROOT / "src")):
    if _p in sys.path:
        sys.path.remove(_p)
    sys.path.insert(0, _p)
import os  # noqa: E402

os.chdir(_ROOT)

from property_profile import build_profile  # noqa: E402

# The team's accuracy benchmark addresses. Keep this list curated + small.
BENCHMARKS = [
    "509 Jefferson St Blacksburg",
    "2027 Peppers Ferry Rd Blacksburg",
    "165 Ash Drive Christiansburg",
    "48th Street Radford",
    "105 Woodbine Dr Blacksburg",
]


def _money(v) -> str:
    return f"${v:,.0f}" if isinstance(v, (int, float)) and v else "—"


def run(ai_hygiene: bool) -> list[dict]:
    rows: list[dict] = []
    for addr in BENCHMARKS:
        try:
            p = build_profile(addr, None, ai_hygiene=ai_hygiene)
        except Exception as e:  # never let one address kill the run
            rows.append({"address": addr, "ok": False, "error": str(e)[:200]})
            continue
        if not p.get("ok"):
            rows.append({"address": addr, "ok": False, "error": p.get("error")})
            continue
        f = p.get("facts") or {}
        v = p.get("valuation") or {}
        sh = p.get("saleHistory") or []
        last = sh[0] if sh else {}
        baths = (f.get("full_baths") or 0) + 0.5 * (f.get("half_baths") or 0)
        rows.append({
            "address": addr,
            "ok": True,
            "resolved": f.get("address"),
            "city": f.get("city"),
            "sqft": f.get("sqft"),
            "beds": f.get("beds"),
            "baths": baths,
            "year_built": f.get("year_built"),
            "acres": f.get("acres"),
            "estimate": v.get("mid"),
            "low": v.get("low"),
            "high": v.get("high"),
            "n_comps": len(p.get("comps") or []),
            "last_sale_price": last.get("price"),
            "last_sale_date": last.get("date"),
        })
    return rows


def _print_table(rows: list[dict], ai_hygiene: bool) -> None:
    model = os.environ.get("CMA_HYGIENE_MODEL", "claude-haiku-4-5-20251001") if ai_hygiene else "(none)"
    print(f"\nCMA BENCHMARKS  —  mode: {'AVM + hygiene' if ai_hygiene else 'deterministic (AVM off)'}  |  hygiene model: {model}\n")
    for r in rows:
        if not r.get("ok"):
            print(f"  ✗ {r['address']}\n      could not value: {r.get('error')}\n")
            continue
        rng = f"{_money(r['low'])} – {_money(r['high'])}"
        facts = f"{r['sqft']} sqft · {r['beds']}bd/{r['baths']:g}ba · {r['year_built']} · {r['acres']}ac"
        sale = (f"last MLS sale {_money(r['last_sale_price'])} ({r['last_sale_date']})"
                if r.get("last_sale_price") else "no MLS-confirmed sale")
        print(f"  {r['address']}")
        print(f"      resolved: {r['resolved']}, {r['city']}  [{facts}]")
        print(f"      ESTIMATE: {_money(r['estimate'])}   range {rng}   ({r['n_comps']} comps)   {sale}\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run the standing CMA accuracy benchmark set.")
    ap.add_argument("--no-hygiene", action="store_true", help="AVM off, no LLM — fast + reproducible")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of the table")
    a = ap.parse_args(argv)
    ai_hygiene = not a.no_hygiene
    rows = run(ai_hygiene)
    if a.json:
        print(json.dumps({"ai_hygiene": ai_hygiene, "results": rows}, indent=2, default=str))
    else:
        _print_table(rows, ai_hygiene)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

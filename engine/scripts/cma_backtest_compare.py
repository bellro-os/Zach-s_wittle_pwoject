"""Compare two CMA backtest JSON reports and print the deltas.

    python -X utf8 scripts/cma_backtest_compare.py OLD.json NEW.json [label]

Lower median |APE| / MAPE / MAE is better; higher PPE10 / PPE20 / coverage is
better. Used by the systematic accuracy-improvement loop to decide keep-vs-revert
after each iteration.
"""
from __future__ import annotations

import json
import sys


def _load(p: str) -> dict:
    return json.load(open(p, encoding="utf-8"))


def _fmt_delta(old: float, new: float, lower_better: bool, pct=True, money=False) -> str:
    d = new - old
    better = (d < 0) if lower_better else (d > 0)
    arrow = "BETTER" if (better and abs(d) > 1e-9) else ("worse" if abs(d) > 1e-9 else "=")
    if money:
        return f"{old:,.0f} -> {new:,.0f}  ({d:+,.0f}) {arrow}"
    suf = "%" if pct else ""
    return f"{old:.2f}{suf} -> {new:.2f}{suf}  ({d:+.2f}) {arrow}"


def _seg(old: dict, new: dict, seg_key: str, order=None) -> None:
    so = old.get("segments", {}).get(seg_key, {})
    sn = new.get("segments", {}).get(seg_key, {})
    keys = order or sorted(set(so) | set(sn))
    print(f"\n  {seg_key}  (median |APE|, lower better):")
    for k in keys:
        o = so.get(k, {})
        n = sn.get(k, {})
        if not o.get("n") and not n.get("n"):
            continue
        oa = o.get("median_ape_pct")
        na = n.get("median_ape_pct")
        if oa is None or na is None:
            print(f"    {k:<12} n {o.get('n','-')}/{n.get('n','-')}  (one side missing)")
            continue
        d = na - oa
        tag = "BETTER" if d < -0.01 else ("worse" if d > 0.01 else "=")
        print(f"    {k:<12} n={n.get('n','-'):<5} {oa:6.2f}% -> {na:6.2f}%  ({d:+6.2f}) {tag}")


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    old = _load(sys.argv[1])
    new = _load(sys.argv[2])
    label = sys.argv[3] if len(sys.argv) > 3 else "comparison"
    oo, no = old["overall"], new["overall"]
    om, nm = old.get("meta", {}), new.get("meta", {})

    print("=" * 72)
    print(f"BACKTEST COMPARISON: {label}")
    print("=" * 72)
    print(f"  scored: {om.get('scored','?')} -> {nm.get('scored','?')}   "
          f"coverage(eligible): {om.get('coverage_pct','?')}% -> {nm.get('coverage_pct','?')}%")
    print("\n  OVERALL:")
    print(f"    median |APE|     : {_fmt_delta(oo['median_ape_pct'], no['median_ape_pct'], True)}")
    print(f"    MAPE             : {_fmt_delta(oo['mape_pct'], no['mape_pct'], True)}")
    print(f"    MAE              : {_fmt_delta(oo['mae'], no['mae'], True, money=True)}")
    print(f"    median abs error : {_fmt_delta(oo['median_abs_error'], no['median_abs_error'], True, money=True)}")
    print(f"    PPE10            : {_fmt_delta(oo['ppe10_pct'], no['ppe10_pct'], False)}")
    print(f"    PPE20            : {_fmt_delta(oo['ppe20_pct'], no['ppe20_pct'], False)}")
    print(f"    interval coverage: {_fmt_delta(oo['interval_coverage_pct'], no['interval_coverage_pct'], False)}")
    print(f"    median signed err: {oo['median_signed_error_pct']:+.2f}% -> {no['median_signed_error_pct']:+.2f}%")
    print(f"    mean signed err  : {oo['mean_signed_error_pct']:+.2f}% -> {no['mean_signed_error_pct']:+.2f}%")

    _seg(old, new, "by_price_band", ["<150k", "150-300k", "300-500k", "500-750k", "750k-1M", "1M+"])
    _seg(old, new, "by_acre_tier", ["<1ac", "1-2ac", "2-6ac", "6-15ac", "15-40ac", "40ac+"])
    _seg(old, new, "by_class", ["RE_1", "LD_3", "CM_4", "MF_2"])

    verdict = "KEEP" if no["median_ape_pct"] < oo["median_ape_pct"] - 0.01 else (
        "REVERT" if no["median_ape_pct"] > oo["median_ape_pct"] + 0.01 else "NEUTRAL (check segments/coverage)")
    print("\n  HEADLINE VERDICT (overall median |APE|):", verdict)
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

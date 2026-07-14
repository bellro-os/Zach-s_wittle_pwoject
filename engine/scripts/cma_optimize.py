"""Parallel hyperparameter search over the CMA valuation + comp-quality knobs,
gated on the leak-free backtest with a train/validation split to prevent
overfitting.

Each candidate config is a set of CMA_* env vars (read at engine import, so every
trial is a fresh subprocess). We sample N random configs, score each on the TRAIN
as-of, rank by a composite accuracy objective, then VALIDATE the top-K on a
held-out as-of and pick the winner that generalizes (best train+val objective)
while holding guardrails (mid-market not regressed, calibration intact).

    python scripts/cma_optimize.py --trials 100 --workers 8

Prints the winning config + train/val metrics vs baseline. Does NOT edit the
engine — the operator bakes the winner's values in as new defaults.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "cma_backtest" / "opt"
TRAIN_ASOF = "2026-06-15"
VAL_ASOF = "2026-03-15"

# Search space. INTERVAL_K is fixed (it only moves interval coverage, tuned
# separately); PPSF_OUTLIER_K is flag-only (value-neutral) so it's not searched.
def sample_config(rng: random.Random) -> dict[str, str]:
    return {
        "CMA_MEDIAN_CAP_K": f"{rng.uniform(1.2, 2.0):.2f}",
        "CMA_AVM_W_MULT": f"{rng.uniform(1.0, 3.0):.2f}",
        "CMA_CLAMP_LO": f"{rng.uniform(0.40, 0.65):.2f}",
        "CMA_CLAMP_HI": f"{rng.uniform(1.40, 1.90):.2f}",
        "CMA_AVM_ENV_HI": f"{rng.uniform(2.0, 3.5):.1f}",
        "CMA_BEDBATH_MAX_DELTA": f"{rng.choice([1, 2, 3])}",
        "CMA_COMP_FLOOR_FRAC": f"{rng.uniform(0.40, 0.75):.2f}",
        "CMA_PPSF_DROP_RATIO": f"{rng.uniform(1.8, 2.6):.2f}",
        "CMA_INTERVAL_K": "2.0",
    }


def run_backtest(tag: str, env_over: dict[str, str], asof: str, limit: int) -> dict | None:
    out_dir = OUT / tag
    env = dict(os.environ)
    env.update(env_over)
    env["PYTHONIOENCODING"] = "utf-8"
    cmd = [sys.executable, "-X", "utf8", "scripts/backtest_cma.py",
           "--as-of-run", asof, "--limit", str(limit),
           "--out", str(out_dir), "--progress-every", "0"]
    try:
        subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, timeout=600)
        j = json.loads((out_dir / "backtest_latest.json").read_text(encoding="utf-8"))
    except Exception:
        return None
    o = j["overall"]
    pb = j["segments"]["by_price_band"]
    mid = pb.get("300-500k", {})
    return {
        "n": o.get("n", 0),
        "medape": o.get("median_ape_pct", 99),
        "mape": o.get("mape_pct", 999),
        "ppe10": o.get("ppe10_pct", 0),
        "ppe20": o.get("ppe20_pct", 0),
        "cover": o.get("interval_coverage_pct", 0),
        "meansigned": o.get("mean_signed_error_pct", 0),
        "coverage_pct": j["meta"].get("coverage_pct", 0),
        "mid_medape": mid.get("median_ape_pct", 99),
    }


def objective(m: dict) -> float:
    """Lower = better. Favor typical-case accuracy (medAPE, PPE10/20), penalize
    the tail (MAPE). Guardrail violations return +inf."""
    if m is None or m["n"] < 100:
        return float("inf")
    if m["mid_medape"] > 10.6 or m["coverage_pct"] < 80 or m["cover"] < 70:
        return float("inf")
    return m["medape"] - 0.35 * m["ppe10"] - 0.15 * m["ppe20"] + 0.12 * m["mape"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=100)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=1000)      # search sample size
    ap.add_argument("--val-limit", type=int, default=1500)  # validation sample size
    ap.add_argument("--topk", type=int, default=12)
    ap.add_argument("--seed", type=int, default=20260617)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    rng = random.Random(a.seed)
    t0 = time.time()

    # Configs: baseline (current baked defaults = empty override) + N random.
    configs = [("baseline", {})]
    for i in range(a.trials):
        configs.append((f"t{i:03d}", sample_config(rng)))

    print(f"[opt] {len(configs)} configs on TRAIN {TRAIN_ASOF} (limit {a.limit}), {a.workers} workers...", flush=True)
    results: dict[str, dict] = {}

    def _train(item):
        tag, ov = item
        m = run_backtest(f"{tag}_tr", ov, TRAIN_ASOF, a.limit)
        return tag, ov, m

    done = 0
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for tag, ov, m in ex.map(_train, configs):
            results[tag] = {"ov": ov, "train": m, "train_obj": objective(m)}
            done += 1
            if done % 10 == 0:
                print(f"[opt]   train {done}/{len(configs)} done ({time.time()-t0:.0f}s)", flush=True)

    ranked = sorted(results.items(), key=lambda kv: kv[1]["train_obj"])
    base = results["baseline"]["train"]
    print(f"\n[opt] BASELINE train: medAPE {base['medape']} MAPE {base['mape']} PPE10 {base['ppe10']} obj {results['baseline']['train_obj']:.3f}")
    print(f"[opt] TOP {a.topk} on train:")
    for tag, r in ranked[:a.topk]:
        m = r["train"]
        if m:
            print(f"   {tag:<10} obj {r['train_obj']:.3f}  medAPE {m['medape']} MAPE {m['mape']} PPE10 {m['ppe10']} PPE20 {m['ppe20']} | {r['ov']}")

    # Validate the top-K (+ baseline) on the held-out as-of.
    topk = [t for t, _ in ranked[:a.topk] if results[t]["train_obj"] != float("inf")]
    if "baseline" not in topk:
        topk.append("baseline")
    print(f"\n[opt] VALIDATING {len(topk)} on held-out {VAL_ASOF} (limit {a.val_limit})...", flush=True)

    def _val(tag):
        m = run_backtest(f"{tag}_val", results[tag]["ov"], VAL_ASOF, a.val_limit)
        return tag, m

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for tag, m in ex.map(_val, topk):
            results[tag]["val"] = m
            results[tag]["val_obj"] = objective(m)

    # Winner = best train+val combined objective among configs that generalize
    # (finite val objective = holds guardrails on BOTH sets).
    cand = [(t, results[t]["train_obj"] + results[t]["val_obj"]) for t in topk
            if results[t].get("val_obj", float("inf")) != float("inf")]
    cand.sort(key=lambda x: x[1])
    print("\n[opt] VALIDATION RESULTS (train_obj + val_obj, lower=better):")
    bv = results["baseline"].get("val", {})
    print(f"   baseline   train+val {results['baseline']['train_obj']+results['baseline'].get('val_obj',float('inf')):.3f}  "
          f"val medAPE {bv.get('medape')} MAPE {bv.get('mape')} PPE10 {bv.get('ppe10')} cover {bv.get('cover')}")
    for t, combo in cand[:a.topk]:
        tr, va = results[t]["train"], results[t]["val"]
        print(f"   {t:<10} combo {combo:.3f}  TR medAPE {tr['medape']}/PPE10 {tr['ppe10']}/MAPE {tr['mape']}  "
              f"VAL medAPE {va['medape']}/PPE10 {va['ppe10']}/MAPE {va['mape']}/cover {va['cover']}")

    if cand:
        win, _ = cand[0]
        print("\n[opt] ===== WINNER =====")
        print(f"   config: {results[win]['ov']}")
        print(f"   TRAIN: {results[win]['train']}")
        print(f"   VAL  : {results[win]['val']}")
        print(f"   BASELINE TRAIN: {base}")
        print(f"   BASELINE VAL  : {bv}")
        (OUT / "winner.json").write_text(json.dumps({
            "winner_tag": win, "config": results[win]["ov"],
            "train": results[win]["train"], "val": results[win]["val"],
            "baseline_train": base, "baseline_val": bv,
        }, indent=2), encoding="utf-8")
    print(f"\n[opt] done in {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

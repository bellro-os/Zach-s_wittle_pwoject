"""Unit tests for the CMA valuation math in ``scripts/build_cma.py``.

Deterministic / network-free / DB-free: every test uses synthetic subject and
comp dicts. The AVM method (``_method_avm``) is monkeypatched off in the
``_estimate_value`` tests so the blend never depends on whether a trained model
file happens to be present on disk — keeping the asserts reproducible.
"""
from __future__ import annotations

from statistics import median

import pytest


# ---------------------------------------------------------------------------
# 1. _eff_acres — concave "effective acres" (the diminishing-land fix)
# ---------------------------------------------------------------------------

def test_eff_acres_identity_at_or_below_homesite_base(build_cma_mod):
    """Identity for acreage at/below the 1-acre homesite base, so the
    dominant small-lot comps (and the rate they calibrate) are unchanged."""
    eff = build_cma_mod._eff_acres
    assert eff(0.0) == 0.0
    assert eff(0.5) == pytest.approx(0.5)
    assert eff(1.0) == pytest.approx(1.0)


def test_eff_acres_concave_above_base(build_cma_mod):
    """Above the base, effective acres grow concavely: well below linear."""
    eff = build_cma_mod._eff_acres
    # eff(2) sits at base + sqrt(1) = 2.0 exactly (boundary of the concave region).
    assert eff(2.0) == pytest.approx(2.0)
    # Strictly below the raw acreage once past the base.
    assert eff(6.0) < 6.0
    # "<< 40" in the docstring means an order of magnitude below: ~7.24 vs 40.
    assert eff(40.0) < 8.0
    assert eff(40.0) < 0.25 * 40.0
    assert eff(15.0) < 5.0          # ~4.74


def test_eff_acres_monotonic_increasing(build_cma_mod):
    """Effective acres never decrease as raw acreage increases."""
    eff = build_cma_mod._eff_acres
    acres = [0.0, 0.5, 1.0, 2.0, 3.0, 6.0, 10.0, 15.0, 25.0, 40.0, 100.0]
    effs = [eff(a) for a in acres]
    assert all(b >= a for a, b in zip(effs, effs[1:]))
    # And it is strictly increasing across these distinct sample points.
    assert all(b > a for a, b in zip(effs, effs[1:]))


def test_eff_acres_matches_documented_anchor_values(build_cma_mod):
    """Pin the documented anchor values so the curve shape can't silently drift."""
    eff = build_cma_mod._eff_acres
    assert eff(6.0) == pytest.approx(3.2361, abs=1e-3)
    assert eff(15.0) == pytest.approx(4.7417, abs=1e-3)
    assert eff(40.0) == pytest.approx(7.245, abs=1e-3)


def test_eff_acres_negative_clamped_to_zero(build_cma_mod):
    """Garbage/negative acreage clamps to 0 rather than producing complex/NaN."""
    eff = build_cma_mod._eff_acres
    assert eff(-5.0) == 0.0
    assert eff(None) == 0.0


# ---------------------------------------------------------------------------
# 2. _method_acreage_residual — land contribution below naive linear
# ---------------------------------------------------------------------------

def _small_lot_comps():
    """~1800 sqft homes on ~1 acre around $300k — small-lot dominated set."""
    return [
        {"sqft": 1800, "acres": 1.0, "sold_price": 300_000},
        {"sqft": 1900, "acres": 1.2, "sold_price": 310_000},
        {"sqft": 1700, "acres": 0.8, "sold_price": 290_000},
        {"sqft": 2000, "acres": 1.5, "sold_price": 320_000},
    ]


def test_acreage_residual_land_contribution_below_naive_linear(build_cma_mod):
    """A large-acreage subject's land contribution must be MATERIALLY below the
    naive linear ``land_rate * acres`` — the over-valuation bug the fix addressed."""
    m = build_cma_mod
    comps = _small_lot_comps()
    subject = {"sqft": 1800, "acres": 40.0}

    result = m._method_acreage_residual(subject, comps)
    assert result.value is not None

    # Reconstruct the model's intermediate quantities exactly the way the
    # method does, to derive the land_rate it used.
    triples = [(c["sqft"], c["acres"], c["sold_price"]) for c in comps]
    improvement_ppsf = median(sp / sf for sf, _ac, sp in triples)
    per_acre = []
    for sf, ac, sp in triples:
        residual = sp - improvement_ppsf * sf
        eff = m._eff_acres(ac)
        if eff > 0 and residual > 0:
            per_acre.append(residual / eff)
    # The 2026-06 calibration damps the residual land rate (_LAND_RESID_MULT).
    land_rate = median(per_acre) * m._LAND_RESID_MULT

    concave_land = land_rate * m._eff_acres(40.0)
    naive_linear_land = land_rate * 40.0

    # The concave land contribution should be a small fraction of the naive one.
    assert concave_land < naive_linear_land
    assert concave_land < 0.30 * naive_linear_land

    # And the method's reported value reflects the concave land term, not the
    # linear one: value = improvement_ppsf*sqft + concave_land.
    improvement_value = improvement_ppsf * subject["sqft"]
    assert result.value == pytest.approx(improvement_value + concave_land, rel=1e-6)
    # Sanity: had it used linear land, value would be far larger.
    assert result.value < improvement_value + naive_linear_land


def test_acreage_residual_none_without_triples(build_cma_mod):
    """No (sqft + acres + price) triple in the comp set -> value=None."""
    m = build_cma_mod
    # Comps missing acres -> no usable triples.
    comps = [{"sqft": 1800, "sold_price": 300_000},
             {"sqft": 1900, "sold_price": 310_000}]
    result = m._method_acreage_residual({"sqft": 1800, "acres": 5.0}, comps)
    assert result.value is None
    assert result.low is None and result.high is None


def test_acreage_residual_none_without_subject_acres(build_cma_mod):
    """A subject lacking acres can't run the land residual -> value=None."""
    m = build_cma_mod
    result = m._method_acreage_residual({"sqft": 1800}, _small_lot_comps())
    assert result.value is None


# ---------------------------------------------------------------------------
# 3. _estimate_value — comp-envelope clamp + None-method drop-out
# ---------------------------------------------------------------------------

@pytest.fixture
def avm_off(build_cma_mod, monkeypatch):
    """Force the AVM method to contribute nothing, so the blend depends only on
    the deterministic comp arithmetic regardless of model-file presence."""
    monkeypatch.setattr(
        build_cma_mod, "_method_avm",
        lambda subject, comps: build_cma_mod.ValuationMethod(
            "AVM (model)", None, None, None, "disabled for test"),
    )


def _envelope_comps():
    """Tight ~$650k-$720k comp set with usable sqft/acres/price/dates."""
    return [
        {"sqft": 2000, "acres": 2.0, "sold_price": 650_000,
         "close_date": "2025-09-01", "original_list_price": 660_000},
        {"sqft": 2200, "acres": 3.0, "sold_price": 700_000,
         "close_date": "2025-10-01", "original_list_price": 710_000},
        {"sqft": 2100, "acres": 2.5, "sold_price": 680_000,
         "close_date": "2025-11-01", "original_list_price": 690_000},
        {"sqft": 2300, "acres": 2.2, "sold_price": 720_000,
         "close_date": "2025-08-01", "original_list_price": 730_000},
    ]


def test_estimate_value_clamped_to_comp_envelope(build_cma_mod, avm_off):
    """A wildly oversized subject would explode $/sqft + acreage methods, but the
    final mid must stay inside the comp envelope (incl. the median-anchored cap)."""
    m = build_cma_mod
    comps = _envelope_comps()
    subject = {"sqft": 16_000, "acres": 24.0}  # the documented blow-up case

    res = m._estimate_value(subject, comps)

    prices = sorted(c["sold_price"] for c in comps)
    lo_cap = prices[0] * m._CLAMP_LO
    hi_cap = prices[-1] * m._CLAMP_HI
    # The 2026-06 calibration additionally anchors the high cap to the median.
    if m._MEDIAN_CAP_K > 0:
        hi_cap = min(hi_cap, median(prices) * m._MEDIAN_CAP_K)
    assert lo_cap <= res.mid <= hi_cap
    assert lo_cap <= res.low <= hi_cap
    assert lo_cap <= res.high <= hi_cap
    # The explosive subject should be pinned at the high cap, proving the clamp
    # actually bit rather than the value coincidentally landing inside.
    # (ValuationResult is unrounded since the rounding-at-render change.)
    assert res.mid == pytest.approx(hi_cap, rel=1e-9)


def test_estimate_value_normal_subject_not_clamped(build_cma_mod, avm_off):
    """A subject sized like its comps lands naturally inside the envelope
    (clamp present but inert) — guards against the clamp dragging normal cases."""
    m = build_cma_mod
    comps = _envelope_comps()
    subject = {"sqft": 2150, "acres": 2.4}
    res = m._estimate_value(subject, comps)
    prices = sorted(c["sold_price"] for c in comps)
    # Comfortably inside the realized comp price range, nowhere near the caps.
    assert prices[0] * 0.9 <= res.mid <= prices[-1] * 1.1


def test_estimate_value_methods_returning_none_drop_out(build_cma_mod, avm_off):
    """When the only data supports no method, mid=0 and nothing raises."""
    m = build_cma_mod
    # Subject has no sqft -> $/sqft, direct comp, acreage residual all None;
    # AVM forced off. No prior MLS sale (no parcel/parquet).
    subject = {"acres": 1.0}
    comps = [{"acres": 1.0, "sold_price": 300_000}]  # no sqft on comps either
    res = m._estimate_value(subject, comps)
    assert res.mid == 0
    assert res.low == 0
    assert res.high == 0
    # All five methods are still surfaced for the report even when none ran,
    # and every one of them is unusable (value is None). NOTE: a method's
    # ``name`` differs by outcome — the land-residual method reports
    # "Land residual" when it can't run vs "Acreage residual" when it can.
    assert len(res.methods) == 5
    assert all(meth.value is None for meth in res.methods)
    assert any(meth.name == "Land residual" for meth in res.methods)


def test_estimate_value_empty_comps_does_not_crash(build_cma_mod, avm_off):
    """An empty comp list returns a zeroed result rather than raising."""
    m = build_cma_mod
    res = m._estimate_value({"sqft": 2000, "acres": 1.0}, [])
    assert res.mid == 0 and res.low == 0 and res.high == 0


# ---------------------------------------------------------------------------
# 4. _triangulation_weights — per-tier weights + acreage-residual growth
# ---------------------------------------------------------------------------

def test_triangulation_weights_suburban_tier(build_cma_mod):
    w = build_cma_mod._triangulation_weights(1.0)
    assert w["Acreage residual"] == pytest.approx(0.10)
    assert w["$/sqft"] == pytest.approx(0.50)
    assert w["Direct comp + acreage adjustment"] == pytest.approx(0.40)
    assert w["AVM (model)"] == pytest.approx(0.30)


def test_triangulation_weights_mid_tier(build_cma_mod):
    w = build_cma_mod._triangulation_weights(5.0)
    assert w["Acreage residual"] == pytest.approx(0.25)
    assert w["$/sqft"] == pytest.approx(0.30)
    assert w["Direct comp + acreage adjustment"] == pytest.approx(0.45)
    assert w["AVM (model)"] == pytest.approx(0.25)


def test_triangulation_weights_rural_tier(build_cma_mod):
    w = build_cma_mod._triangulation_weights(20.0)
    assert w["Acreage residual"] == pytest.approx(0.45)
    assert w["$/sqft"] == pytest.approx(0.15)
    assert w["Direct comp + acreage adjustment"] == pytest.approx(0.40)
    assert w["AVM (model)"] == pytest.approx(0.20)


def test_triangulation_acreage_residual_weight_increases_with_acreage(build_cma_mod):
    """The acreage-residual weight rises monotonically across the three tiers:
    0.10 (<2ac) -> 0.25 (mid) -> 0.45 (>=15ac)."""
    m = build_cma_mod
    low = m._triangulation_weights(1.0)["Acreage residual"]
    mid = m._triangulation_weights(5.0)["Acreage residual"]
    high = m._triangulation_weights(20.0)["Acreage residual"]
    assert low < mid < high


def test_triangulation_weights_tier_boundaries(build_cma_mod):
    """Boundary behavior: 2.0 leaves the suburban tier; 15.0 enters rural."""
    m = build_cma_mod
    assert m._triangulation_weights(1.99)["Acreage residual"] == pytest.approx(0.10)
    assert m._triangulation_weights(2.0)["Acreage residual"] == pytest.approx(0.25)
    assert m._triangulation_weights(14.99)["Acreage residual"] == pytest.approx(0.25)
    assert m._triangulation_weights(15.0)["Acreage residual"] == pytest.approx(0.45)


# ---------------------------------------------------------------------------
# 6. Helper sanity — _round_to_5k and _num
# ---------------------------------------------------------------------------

def test_round_to_5k_rounds_to_nearest_5000(build_cma_mod):
    r = build_cma_mod._round_to_5k
    assert r(123_456) == 125_000
    assert r(122_499) == 120_000
    assert r(0) == 0
    assert r(300_000) == 300_000


def test_round_to_5k_returns_int(build_cma_mod):
    assert isinstance(build_cma_mod._round_to_5k(123_456.78), int)


def test_num_coerces_and_rejects_garbage(build_cma_mod):
    n = build_cma_mod._num
    assert n("123.5") == pytest.approx(123.5)
    assert n(10) == 10.0
    assert n("") is None
    assert n(None) is None
    assert n("not-a-number") is None
    assert n(float("nan")) is None

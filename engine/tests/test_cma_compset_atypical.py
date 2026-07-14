"""Unit tests for ``cma_compset._atypical_signals`` (and a couple of nearby
scoring helpers).

Network-free / DB-free: synthetic comp dicts only. Reason strings are matched
on stable substrings (the source uses an em-dash that we deliberately don't
hard-code) so the tests don't break on punctuation/encoding churn.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# 5. _atypical_signals
# ---------------------------------------------------------------------------

def test_atypical_sold_well_below_list(compset_mod):
    """(a) sold/list ratio below 0.85 -> atypical (possibly distressed)."""
    atypical, reason = compset_mod._atypical_signals(
        {"sold_price": 80_000, "original_list_price": 100_000}
    )
    assert atypical is True
    assert "below list" in reason


def test_atypical_sold_above_list(compset_mod):
    """sold/list ratio above 1.05 -> atypical (competitive multi-bid)."""
    atypical, reason = compset_mod._atypical_signals(
        {"sold_price": 110_000, "original_list_price": 100_000}
    )
    assert atypical is True
    assert "above list" in reason


def test_atypical_below_prior_deed_price(compset_mod):
    """(b) sold ~normal vs list but well under the prior recorded deed price
    (< 0.55 x deed_last_sale_price) -> atypical with the deed-ratio reason.

    This is the NEW deed-ratio branch. The sold/list ratio (0.95) is healthy,
    so the only thing that can flag this comp is the deed comparison."""
    comp = {
        "sold_price": 95_000,            # 95% of list -> NOT flagged by sold/list
        "original_list_price": 100_000,
        "deed_last_sale_price": 250_000,  # sold is 38% of prior deed -> flag
    }
    # Confirm the sold/list branch alone would pass (not atypical) ...
    sl_only = {k: comp[k] for k in ("sold_price", "original_list_price")}
    assert compset_mod._atypical_signals(sl_only) == (False, "")
    # ... so the deed branch is what fires here.
    atypical, reason = compset_mod._atypical_signals(comp)
    assert atypical is True
    assert "prior deed price" in reason


def test_atypical_deed_branch_not_triggered_when_close_to_deed(compset_mod):
    """A sale at/above ~55% of the prior deed price does NOT trip the deed branch."""
    comp = {
        "sold_price": 200_000,
        "original_list_price": 205_000,   # healthy sold/list
        "deed_last_sale_price": 250_000,  # 80% of deed -> well above the 0.55 floor
    }
    atypical, reason = compset_mod._atypical_signals(comp)
    assert atypical is False
    assert reason == ""


def test_clean_arms_length_not_atypical(compset_mod):
    """(c) sold ~= list, no deed red flag, normal DOM -> NOT atypical."""
    comp = {
        "sold_price": 99_000,
        "original_list_price": 100_000,   # 99% of list
        "deed_last_sale_price": 95_000,   # sold > prior deed, no distress
        "dom": 21,
    }
    assert compset_mod._atypical_signals(comp) == (False, "")


def test_atypical_long_marketing_period(compset_mod):
    """DOM > 180 -> atypical (listing fatigue)."""
    atypical, reason = compset_mod._atypical_signals({"dom": 200})
    assert atypical is True
    assert "DOM" in reason


def test_dom_at_threshold_not_atypical(compset_mod):
    """DOM exactly 180 is the boundary and must NOT flag (strict > 180)."""
    atypical, _ = compset_mod._atypical_signals({"dom": 180})
    assert atypical is False


@pytest.mark.parametrize("comp", [
    {},
    {"sold_price": None, "original_list_price": None, "dom": None,
     "deed_last_sale_price": None},
    {"sold_price": "garbage", "original_list_price": "junk"},
    {"sold_price": 100_000, "original_list_price": 0},          # zero list price
    {"sold_price": 100_000, "deed_last_sale_price": 500},        # deed below $1000 guard
    {"dom": "n/a"},
])
def test_atypical_missing_or_bad_fields_never_raise(compset_mod, comp):
    """(d) missing/None/garbage fields never raise; default is not-atypical."""
    atypical, reason = compset_mod._atypical_signals(comp)
    assert atypical is False
    assert reason == ""


def test_atypical_sold_list_precedence_over_deed(compset_mod):
    """The sold/list branch is evaluated first: a comp that trips BOTH the
    sold/list and the deed branch returns the sold/list reason."""
    comp = {
        "sold_price": 70_000,
        "original_list_price": 100_000,   # 70% of list -> sold/list fires first
        "deed_last_sale_price": 250_000,  # would also fire the deed branch
    }
    atypical, reason = compset_mod._atypical_signals(comp)
    assert atypical is True
    assert "below list" in reason          # sold/list reason, not deed reason


# ---------------------------------------------------------------------------
# Nearby cheap helpers — tier bucketing used by diversity selection
# ---------------------------------------------------------------------------

def test_acre_tier_buckets(compset_mod):
    t = compset_mod._acre_tier
    assert t(None) == "?"
    assert t(0.5) == "<2ac"
    assert t(1.99) == "<2ac"
    assert t(2.0) == "2-6ac"
    assert t(6.0) == "6-15ac"
    assert t(15.0) == "15-40ac"
    assert t(40.0) == "40ac+"


def test_proximity_neutral_on_missing(compset_mod):
    """Missing inputs yield the neutral 0.5; identical inputs yield ~1.0."""
    p = compset_mod._proximity
    assert p(None, 100.0, 50.0) == 0.5
    assert p(100.0, None, 50.0) == 0.5
    assert p(100.0, 100.0, 50.0) == pytest.approx(1.0)
    # Monotone decay: farther apart -> lower proximity.
    assert p(100.0, 150.0, 50.0) < p(100.0, 120.0, 50.0)

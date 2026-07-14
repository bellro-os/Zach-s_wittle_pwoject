"""Price-band definitions per property class.

Bands are inclusive of the lower bound, exclusive of the upper. The label is
"$LO-$HI" or "$HI+" for the open-ended top.
"""

from __future__ import annotations


# Residential / multifamily / rental — wider bands at the top
RES_BANDS = [
    (0, 100_000),
    (100_000, 150_000),
    (150_000, 200_000),
    (200_000, 250_000),
    (250_000, 300_000),
    (300_000, 350_000),
    (350_000, 400_000),
    (400_000, 500_000),
    (500_000, 600_000),
    (600_000, 750_000),
    (750_000, 1_000_000),
    (1_000_000, 1_500_000),
    (1_500_000, float("inf")),
]

# Land — much smaller dollar amounts, $25k bands at the low end
LAND_BANDS = [
    (0, 25_000),
    (25_000, 50_000),
    (50_000, 75_000),
    (75_000, 100_000),
    (100_000, 150_000),
    (150_000, 200_000),
    (200_000, 300_000),
    (300_000, 500_000),
    (500_000, 1_000_000),
    (1_000_000, float("inf")),
]

# Commercial / farm — variable
COMM_BANDS = [
    (0, 100_000),
    (100_000, 250_000),
    (250_000, 500_000),
    (500_000, 1_000_000),
    (1_000_000, 2_500_000),
    (2_500_000, 5_000_000),
    (5_000_000, float("inf")),
]


BANDS_BY_CLASS = {
    "RE_1": RES_BANDS,
    "MF_2": RES_BANDS,
    "LD_3": LAND_BANDS,
    "CM_4": COMM_BANDS,
    "FM_5": COMM_BANDS,
    "RN_6": RES_BANDS,
}


def label(lo: float, hi: float) -> str:
    if hi == float("inf"):
        return f"${int(lo/1000)}k+"
    return f"${int(lo/1000)}-${int(hi/1000)}k"


def band_for(price: float | int | None, class_id: str) -> str | None:
    if price is None:
        return None
    try:
        p = float(price)
    except (TypeError, ValueError):
        return None
    if p <= 0:
        return None
    bands = BANDS_BY_CLASS.get(class_id, RES_BANDS)
    for lo, hi in bands:
        if lo <= p < hi:
            return label(lo, hi)
    return None


def all_labels(class_id: str) -> list[str]:
    return [label(lo, hi) for lo, hi in BANDS_BY_CLASS.get(class_id, RES_BANDS)]

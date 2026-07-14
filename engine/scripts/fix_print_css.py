"""Patch print CSS in existing Gravity-branded HTML reports.

Removes the broken patterns:
  - .body { flex:1; display:flex; flex-direction:column; justify-content:space-between }
  - .page { height:11in; max-height:11in; overflow:hidden } in print
  - html,body { overflow:hidden; line-height:0 } in print

Replaces with:
  - .body { display: block; flex: 1 } (no space-between, no flex-direction)
  - .page { min-height:11in; page-break-after:always } in print
  - Plus page-break-inside:avoid on tables/blocks
"""
from __future__ import annotations

import re
from pathlib import Path

REPORTS = [
    "outputs/cma_parcel_031651_deerfield_pdr.html",
    "outputs/cma_7423_floyd_hwy_copper_hill.html",
    "outputs/cma_680_mt_pleasant_shawsville.html",
    "outputs/cma_6431_teeth_of_the_dog_radford.html",
    "outputs/market_report_fiddlers_green_blacksburg.html",
    "outputs/buyer_inventory_4_5br_under_600k.html",
    "outputs/buyer_inventory_4_5br_floyd_montgomery.html",
]


def patch(html: str) -> tuple[str, list[str]]:
    """Apply the print-CSS fixes. Returns (new_html, applied_changes)."""
    changes: list[str] = []
    orig = html

    # Fix 1: .body — drop space-between + flex-direction:column.
    # Patterns vary slightly across files (some have flex:1, some don't).
    new = re.sub(
        r"\.body\{padding:([^;]+);flex:1;display:flex;flex-direction:column;justify-content:space-between;\}",
        r".body{padding:\1;display:block;}",
        html,
    )
    if new != html:
        changes.append("body: removed flex/space-between")
        html = new

    # Fix 2: @media print .page — replace height:11in/max-height:11in/overflow:hidden
    # with min-height:11in + page-break-after:always.
    new = re.sub(
        r"\.page\{margin:0;box-shadow:none;width:8\.5in;height:11in;min-height:0;max-height:11in;overflow:hidden;line-height:1\.42;\}",
        ".page{margin:0;box-shadow:none;width:8.5in;min-height:11in;page-break-after:always;line-height:1.42;}",
        html,
    )
    if new != html:
        changes.append("print.page: height:11in -> min-height:11in + page-break-after")
        html = new

    # Variant: the 2-page report buyer_inventory_4_5br_floyd_montgomery had:
    # .page{margin:0;box-shadow:none;width:8.5in;height:11in;line-height:1.4;}
    new = re.sub(
        r"\.page\{margin:0;box-shadow:none;width:8\.5in;height:11in;line-height:1\.(4|42);\}",
        r".page{margin:0;box-shadow:none;width:8.5in;min-height:11in;page-break-after:always;line-height:1.\1;}",
        html,
    )
    if new != html:
        changes.append("print.page (2pg variant): height:11in -> min-height:11in + page-break-after")
        html = new

    # Fix 3: html,body in print — drop overflow:hidden and line-height:0
    new = re.sub(
        r"html,body\{margin:0;padding:0;background:#fff;font-size:9\.5px;overflow:hidden;line-height:0;\}",
        "html,body{margin:0;padding:0;background:#fff;font-size:9.5px;}",
        html,
    )
    if new != html:
        changes.append("print html,body: removed overflow:hidden + line-height:0")
        html = new

    # Variant in 2-page report
    new = re.sub(
        r"html,body\{margin:0;padding:0;background:#fff;overflow:hidden;line-height:0;\}",
        "html,body{margin:0;padding:0;background:#fff;}",
        html,
    )
    if new != html:
        changes.append("print html,body (variant): removed overflow:hidden + line-height:0")
        html = new

    # Fix 4: ensure :last-child page-break-after:auto rule exists for multi-page reports.
    # Add page-break-inside:avoid block right before the closing `}` of @media print.
    # We add: .page:last-child{page-break-after:auto;} + page-break-inside:avoid; on key blocks
    # only if the html still has .page:nth-child or buyer_inventory or 2-page suggestion.
    # Simpler: add the page-break-inside block right before the closing brace of @media print {...}
    # by finding the pattern `*{-webkit-print-color-adjust:exact;print-color-adjust:exact;}}`
    pb_rules = (
        ".page:last-child{page-break-after:auto;}"
        "table,tr,thead,tbody{page-break-inside:avoid;}"
        ".hero,.kpis,.kpi,.chart,.panel,.subject,.verdict,.exec,.foot{page-break-inside:avoid;}"
    )
    new = re.sub(
        r"(\*\{-webkit-print-color-adjust:exact;print-color-adjust:exact;\})\}\}",
        r"\1" + pb_rules + "}}",
        html,
    )
    if new != html:
        changes.append("added page-break-inside:avoid on tables/blocks + last-child auto")
        html = new
    else:
        # Try variant without closing }}
        new = re.sub(
            r"(\*\{-webkit-print-color-adjust:exact;print-color-adjust:exact;\}\})",
            pb_rules + r"\1",
            html,
        )
        if new != html:
            changes.append("added page-break-inside:avoid (variant)")
            html = new

    return html, changes


def main():
    root = Path(__file__).resolve().parent.parent
    for rel in REPORTS:
        p = root / rel
        if not p.exists():
            print(f"  SKIP (not found): {rel}")
            continue
        orig = p.read_text(encoding="utf-8")
        new, changes = patch(orig)
        if new == orig:
            print(f"  NO CHANGE: {rel}")
        else:
            p.write_text(new, encoding="utf-8")
            print(f"  PATCHED: {rel}")
            for c in changes:
                print(f"    - {c}")


if __name__ == "__main__":
    main()

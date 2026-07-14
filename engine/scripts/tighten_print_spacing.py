"""Add a print-only spacing override block to compress content for borderline 1-pagers.

Inserts a single compact CSS rule block at the end of the existing @media print
block in each target file. The rule tightens body padding, section margins,
table padding, and footer padding. Designed to shave ~10-15% vertical space.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

TARGETS = [
    "outputs/cma_680_mt_pleasant_shawsville.html",
    "outputs/cma_6431_teeth_of_the_dog_radford.html",
    "outputs/market_report_fiddlers_green_blacksburg.html",
    "outputs/cma_parcel_031651_deerfield_pdr.html",
]

TIGHT = (
    ".body{padding:10px 26px 12px !important;}"
    ".exec{margin:0 0 8px !important;}"
    ".kpis{margin:0 0 8px !important;}"
    ".hero{margin:0 0 10px !important;}"
    "h2.sec{margin:0 0 4px !important;padding-bottom:2px !important;}"
    "table{margin:0 0 6px !important;}"
    "tbody td{padding:3px 5px !important;}"
    "thead th{padding:0 5px 2px !important;}"
    ".charts{margin:0 0 8px !important;}"
    ".chart{padding:7px 11px !important;}"
    ".panel{padding:8px 11px !important;}"
    ".twocol{gap:12px !important;margin-bottom:8px !important;}"
    ".rec{padding:8px 11px !important;}"
    ".foot{padding:9px 30px 10px !important;}"
    ".foot .sig{margin-bottom:5px !important;}"
    ".kpi{padding:6px 9px !important;}"
    ".kpi .n{font-size:14px !important;}"
    ".kpi .l{margin-top:2px !important;}"
    ".titleblock{padding:9px 30px 0 !important;}"
    ".rule{margin-top:8px !important;}"
)


def patch(html: str) -> tuple[str, bool]:
    # Find the @media print { ... } block and append TIGHT just before its closing brace.
    # Strategy: find pattern of the page-break-inside:avoid rules ending with }}
    # and insert TIGHT right before the final }}
    pattern = (
        r"(\.page:last-child\{page-break-after:auto;\}"
        r"table,tr,thead,tbody\{page-break-inside:avoid;\}"
        r"\.hero,\.kpis,\.kpi,\.chart,\.panel,\.subject,\.verdict,\.exec,\.foot\{page-break-inside:avoid;\}"
        r"\*\{-webkit-print-color-adjust:exact;print-color-adjust:exact;\})"
    )
    if re.search(pattern, html) is None:
        return html, False
    # Avoid double-insertion
    if TIGHT[:30] in html:
        return html, False
    new = re.sub(pattern, r"\1" + TIGHT, html, count=1)
    return new, new != html


def main():
    for rel in TARGETS:
        p = ROOT / rel
        if not p.exists():
            print(f"  SKIP: {rel}")
            continue
        old = p.read_text(encoding="utf-8")
        new, changed = patch(old)
        if changed:
            p.write_text(new, encoding="utf-8")
            print(f"  TIGHTENED: {rel}")
        else:
            print(f"  NO CHANGE: {rel}")


if __name__ == "__main__":
    main()

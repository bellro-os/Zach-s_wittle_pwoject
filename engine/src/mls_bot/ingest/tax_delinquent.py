"""Tax-delinquency ingest framework.

NRV counties don't expose delinquent-tax data via API. They publish lists as
PDF notices (typically before each Treasurer's tax-sale auction, ~once per
year). This module provides:

  1. A per-county adapter that parses dropped PDFs into a normalized JSONL
  2. A loader for seller_scoring.py to consume

Usage workflow:
  - Download the most recent delinquent-tax PDF for each county into
    `data/delinquent_tax_pdfs/<county>_<year>.pdf`
  - Run `python tasks.py nrv-pull-delinquent`
  - The loader emits `data/parcel_delinquent.jsonl` keyed on (county, parcel_id)

PDF formats vary year-to-year, so the per-county parsers are intentionally
lenient — they extract any rows matching plausible parcel/account/owner
patterns. Spot-check the JSONL before consuming it.

Resources:
  - Montgomery: https://taxva.com/rs-tax-sales/montgomery-county-real-estate-tax-sale/
                (PDF released ~3 weeks before each auction)
  - Pulaski:    https://www.pulaskicountytax.com/taxes  (no published list —
                FOIA may be required)
  - Floyd / Giles / Radford: published in local newspapers; PDFs sometimes
                available on the Treasurer's page directly
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path


PDF_DIR = Path("data/delinquent_tax_pdfs")
OUT_PATH = Path("data/parcel_delinquent.jsonl")


# Patterns to extract a parcel-id-like token + dollar amount from a PDF row.
# Lenient by design — better to over-capture and let the cross-reference step
# discard rows that don't join to a real parcel.
_PARCEL_AMT_RE = re.compile(
    r"(?P<pid>[\dA-Z][\d\-A-Z\(\)\.\s]{2,30}?)\s+"      # parcel-like token
    r"(?P<rest>.+?)"                                      # owner/addr/etc
    r"\$\s*(?P<amount>[\d,]+\.\d{2})",                  # dollar amount at row end
    re.MULTILINE,
)


def _parse_pdf(pdf_path: Path, county: str) -> list[dict]:
    """Extract candidate (parcel_id, owner, amount) rows from a PDF.

    Returns a list of dicts. The parcel_id is normalized (uppercase, strip
    spaces) but otherwise raw — caller is responsible for cross-referencing
    against the canonical parcel set.
    """
    try:
        import pdfplumber
    except ImportError as e:
        raise RuntimeError("pdfplumber not installed; run: pip install pdfplumber") from e

    rows: list[dict] = []
    with pdfplumber.open(pdf_path) as pdf:
        for pno, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            for m in _PARCEL_AMT_RE.finditer(text):
                pid = re.sub(r"\s+", " ", m.group("pid")).strip().upper()
                rest = m.group("rest").strip()
                try:
                    amt = float(m.group("amount").replace(",", ""))
                except ValueError:
                    continue
                if amt < 50:        # filter noise
                    continue
                if len(pid) < 4:    # filter dates/page numbers
                    continue
                rows.append({
                    "county": county,
                    "parcel_id_raw": pid,
                    "owner_or_addr_raw": rest[:200],
                    "delinquent_amount": amt,
                    "source_pdf": pdf_path.name,
                    "source_page": pno,
                })
    return rows


def ingest_all(*, pdf_dir: Path = PDF_DIR) -> dict:
    """Walk PDF_DIR, parse every PDF, write the normalized JSONL.

    Returns summary dict. If PDF_DIR is empty, writes an empty JSONL and
    returns counts of zero so downstream code degrades gracefully.
    """
    pdf_dir.mkdir(parents=True, exist_ok=True)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(pdf_dir.glob("*.pdf"))
    n_total = 0
    per_county: dict[str, int] = {}
    with OUT_PATH.open("w", encoding="utf-8") as out:
        for pdf in pdfs:
            # Filename convention: <county>_<year>.pdf — leading token is the county
            stem = pdf.stem
            county = stem.split("_")[0].upper()
            try:
                rows = _parse_pdf(pdf, county)
            except Exception as e:
                print(f"  [tax_delinquent] {pdf.name}: parse failed — {e}")
                continue
            for r in rows:
                out.write(json.dumps(r) + "\n")
            n_total += len(rows)
            per_county[county] = per_county.get(county, 0) + len(rows)

    return {
        "pdf_count": len(pdfs),
        "delinquent_rows_extracted": n_total,
        "rows_by_county": per_county,
        "out_path": str(OUT_PATH),
        "pdf_dir": str(pdf_dir),
    }


def load_delinquent_parcel_ids() -> set[tuple[str, str]]:
    """Reader for seller_scoring.

    Returns the set of (county, parcel_id) flagged as tax-delinquent.
    Cross-references the raw parcel_id_raw token against the canonical
    parcel set in `data/<county>_parcels.jsonl` for fuzzy match (parcel
    IDs may have stray spaces or hyphens in PDF formatting).
    """
    if not OUT_PATH.exists():
        return set()

    # Build canonical parcel-id index per county for fuzzy match
    canonical: dict[str, set[str]] = {}
    parcel_files = {
        "MONTGOMERY": "data/montgomery_county_parcels.jsonl",
        "PULASKI":    "data/pulaski_county_parcels.jsonl",
        "FLOYD":      "data/floyd_county_parcels.jsonl",
        "GILES":      "data/giles_county_parcels.jsonl",
        "RADFORD":    "data/radford_city_parcels.jsonl",
    }
    for county, src in parcel_files.items():
        sp = Path(src)
        if not sp.exists():
            continue
        s: set[str] = set()
        with sp.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                pid = (r.get("parcel_id") or "").strip().upper()
                if pid:
                    s.add(pid)
                    s.add(re.sub(r"[\s\-]", "", pid))   # space/hyphen-stripped variant
        canonical[county] = s

    out: set[tuple[str, str]] = set()
    with OUT_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            county = (r.get("county") or "").upper()
            raw = (r.get("parcel_id_raw") or "").upper().strip()
            cand = re.sub(r"[\s\-]", "", raw)
            cset = canonical.get(county) or set()
            if raw in cset:
                out.add((county, raw))
            elif cand in cset:
                out.add((county, cand))
    return out


def load_delinquent_amounts() -> dict[tuple[str, str], float]:
    """Reader for seller_scoring — returns total delinquent $ per parcel."""
    out: dict[tuple[str, str], float] = {}
    if not OUT_PATH.exists():
        return out
    matched = load_delinquent_parcel_ids()
    if not matched:
        return out
    # Re-walk to attach amounts to matched parcels
    with OUT_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            county = (r.get("county") or "").upper()
            raw = (r.get("parcel_id_raw") or "").upper().strip()
            cand = re.sub(r"[\s\-]", "", raw)
            try:
                amt = float(r.get("delinquent_amount") or 0)
            except (TypeError, ValueError):
                continue
            for key in ((county, raw), (county, cand)):
                if key in matched:
                    out[key] = out.get(key, 0.0) + amt
                    break
    return out

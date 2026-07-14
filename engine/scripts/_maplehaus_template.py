"""Compatibility shim — Maplehaus brand helpers.

This module is preserved so existing report builders that ``from
_maplehaus_template import PRINT_CSS, MAPLEHAUS_PALETTE, render_to_pdf`` keep
working unchanged.

All real work now lives in :mod:`mls_bot.brand` and :mod:`mls_bot.skeletons`,
with brand-specific values loaded from ``config/brands/maplehaus.yaml``. New
report code should import directly from those modules.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make `import mls_bot.*` work when this script is imported from anywhere
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mls_bot.brand import Brand  # noqa: E402


_BRAND = Brand.load("maplehaus")

# ---------------------------------------------------------------------------
# Backwards-compatible exports
# ---------------------------------------------------------------------------

MAPLEHAUS_PALETTE: dict[str, str] = {
    # Preserve the original key names some report builders read directly.
    "sage":       _BRAND.palette["primary"],
    "mauve":      _BRAND.palette["secondary"],
    "cream":      _BRAND.palette["paper"],
    "ink":        _BRAND.palette["ink"],
    "beige":      _BRAND.palette["accent"],
    "sage_light": _BRAND.palette.get("primary_light", _BRAND.palette["primary"]),
    "sage_dk":    _BRAND.palette.get("slate", _BRAND.palette["primary"]),
    "rule":       _BRAND.palette["rule"],
    "muted":      _BRAND.palette["muted"],
    "good":       _BRAND.palette["good"],
    "flag":       _BRAND.palette["flag"],
}


PRINT_CSS: str = _BRAND.print_css()


def render_to_pdf(html_path, pdf_path,
                  chrome=r"C:\Program Files\Google\Chrome\Application\chrome.exe") -> int:
    """Headless render. Returns page count parsed from PDF."""
    import subprocess
    import re

    html_path = Path(html_path).resolve()
    pdf_path = Path(pdf_path).resolve()
    url = "file:///" + str(html_path).replace("\\", "/").replace(" ", "%20")
    subprocess.run([
        chrome, "--headless", "--disable-gpu", "--no-pdf-header-footer",
        f"--print-to-pdf={pdf_path}", url,
    ], capture_output=True)
    d = pdf_path.read_bytes()
    counts = re.findall(rb"/Count\s+(\d+)", d)
    return int(counts[0]) if counts else 0


def brand() -> Brand:
    """Return the underlying Brand object for callers that want full access."""
    return _BRAND


__all__ = ["MAPLEHAUS_PALETTE", "PRINT_CSS", "render_to_pdf", "brand"]

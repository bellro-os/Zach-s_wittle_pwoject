"""Compatibility shim — Gravity brand helpers.

This module is preserved so existing report builders that ``from _gravity_template
import PRINT_CSS, GRAVITY_PALETTE, inject_lockup, lockup_data_uri, render_to_pdf``
keep working unchanged.

All real work now lives in :mod:`mls_bot.brand` and :mod:`mls_bot.skeletons`, with
brand-specific values loaded from ``config/brands/gravity.yaml``. New report
code should import directly from those modules.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make `import mls_bot.*` work when this script is imported from anywhere
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mls_bot.brand import Brand  # noqa: E402


_BRAND = Brand.load("gravity")

# ---------------------------------------------------------------------------
# Backwards-compatible exports
# ---------------------------------------------------------------------------

GRAVITY_PALETTE: dict[str, str] = {
    # Preserve the original key names some report builders read directly.
    "ink":       _BRAND.palette["ink"],
    "slate":     _BRAND.palette.get("slate", "#4a4a52"),
    "muted":     _BRAND.palette["muted"],
    "line":      _BRAND.palette["rule"],
    "paper":     _BRAND.palette["paper"],
    "band":      _BRAND.palette["band"],
    "violet":    _BRAND.palette["primary"],
    "violet_d":  _BRAND.palette["secondary"],
    "violet_t":  _BRAND.palette["accent"],
    "violet_tt": _BRAND.palette.get("accent_tint", _BRAND.palette["accent"]),
    "good":      _BRAND.palette["good"],
    "flag":      _BRAND.palette["flag"],
}


# Generated lazily so the @import line + :root block + skeleton are always
# in sync with whatever the YAML currently says.
PRINT_CSS: str = _BRAND.print_css()


def lockup_data_uri(logo_path: str | Path = "Gravity-FullLockup-360-White.png") -> str:
    """Read a PNG file and return a data: URI suitable for an <img src>."""
    # If the caller passes the default path, delegate to the brand object so
    # behaviour stays in sync with the YAML.
    if str(logo_path) == "Gravity-FullLockup-360-White.png":
        uri = _BRAND.logo_data_uri()
        if uri:
            return uri
    # Fall back to the original implementation for non-default paths.
    import base64
    p = Path(logo_path)
    if not p.is_absolute() and not p.exists():
        project_root = Path(__file__).resolve().parent.parent
        candidate = project_root / logo_path
        if candidate.exists():
            p = candidate
    data = p.read_bytes()
    return "data:image/png;base64," + base64.b64encode(data).decode()


def inject_lockup(html: str, logo_path: str | Path = "Gravity-FullLockup-360-White.png",
                  placeholder: str = "__LOCKUP__") -> str:
    """Replace every occurrence of ``placeholder`` in ``html`` with the logo data URI."""
    return html.replace(placeholder, lockup_data_uri(logo_path))


def render_to_pdf(html_path: str | Path, pdf_path: str | Path,
                  chrome_path: str = r"C:\Program Files\Google\Chrome\Application\chrome.exe") -> int:
    """Render an HTML file to PDF via headless Chrome. Returns parsed page count."""
    import subprocess
    import re

    html_path = Path(html_path).resolve()
    pdf_path = Path(pdf_path).resolve()
    file_url = "file:///" + str(html_path).replace("\\", "/").replace(" ", "%20")

    subprocess.run([
        chrome_path, "--headless", "--disable-gpu", "--no-pdf-header-footer",
        f"--print-to-pdf={pdf_path}", file_url,
    ], check=False, capture_output=True)

    data = pdf_path.read_bytes()
    counts = re.findall(rb"/Count\s+(\d+)", data)
    return int(counts[0]) if counts else 0


def brand() -> Brand:
    """Return the underlying Brand object for callers that want full access."""
    return _BRAND


__all__ = [
    "GRAVITY_PALETTE",
    "PRINT_CSS",
    "lockup_data_uri",
    "inject_lockup",
    "render_to_pdf",
    "brand",
]

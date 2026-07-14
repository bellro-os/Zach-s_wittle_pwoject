"""Brand profile loader for white-label CMA / report generation.

Each brand is defined by a YAML file under ``config/brands/<name>.yaml`` and
contains a semantic palette, typography stack, layout style identifier, and
identity assets (wordmark text or logo PNG path).

The :class:`Brand` object knows how to:
  - load itself from disk (:meth:`Brand.load`)
  - emit a full CSS string ready for embedding in an HTML report
    (:meth:`Brand.print_css`)
  - render the masthead and footer-brand HTML blocks that vary between
    layout styles (:meth:`Brand.masthead_html`, :meth:`Brand.footer_brand_html`)

The layout style picks among a small set of canonical skeleton stylesheets
shipped in ``scripts/_print_skeleton.py``. Today supported:

  * ``dark_band`` — black mastbar + PNG lockup + violet accents (Gravity)
  * ``cream_serif`` — cream page + text wordmark + serif display (Maplehaus)

Adding a new agent's brand is YAML-only as long as the brand uses one of the
supported layout styles. A genuinely new visual treatment requires adding a
new entry to ``SKELETONS`` in ``scripts/_print_skeleton.py``.
"""
from __future__ import annotations

import base64
import html as _html
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


def _esc(value) -> str:
    """HTML-escape a tenant/agent-controlled STRING before it enters the report
    HTML. This is the XSS boundary for every brand-identity field (company /
    agent name, wordmark, tagline, disclaimer, license, brokerage, etc.) — the
    saved BrandProfile is tenant-controlled and its values are interpolated into
    the report template that a root headless Chromium renders, so unescaped
    markup here is stored XSS on the render host (SSRF / local-file-read risk).

    Escapes ``&``, ``<``, ``>`` and both quote characters so the value is safe in
    element text AND inside a double-quoted attribute (e.g. ``alt="..."``).
    Normal brand values contain none of these characters, so the visible output
    is byte-identical for valid input."""
    return _html.escape(str(value if value is not None else ""), quote=True)


# Resolve the project root from this file's location: src/mls_bot/brand.py
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_BRANDS_DIR = _PROJECT_ROOT / "config" / "brands"


# Hex color validation (#RGB or #RRGGBB). Used by Brand.from_profile to reject
# garbage tenant input and fall back to a neutral default instead of emitting an
# invalid CSS custom property that would break the skeleton render.
_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

# Safe CSS color pattern for the :root{} palette export. A palette value is
# interpolated RAW into a CSS custom property (``--brand-x: <value>;``), so a
# malicious value like ``red;} body{background:url(...)`` would break out of the
# declaration and inject arbitrary CSS into the root-Chromium render. We only
# emit values that match a hex color (#RGB/#RRGGBB/#RRGGBBAA), an rgb()/rgba()/
# hsl()/hsla() function over digits/commas/%/./spaces, or a plain alphabetic
# named color — none of which can contain the ``;`` / ``}`` / ``:`` / parenthesis-
# with-payload needed to escape the declaration. Anything else is dropped and
# the token simply isn't exported (the skeleton's own fallback applies). Every
# shipped/default palette value matches, so valid brands are visually identical.
_SAFE_CSS_COLOR_RE = re.compile(
    r"^(?:#[0-9a-fA-F]{3,8}"
    r"|(?:rgb|rgba|hsl|hsla)\(\s*[0-9.,%\s]+\)"
    r"|[a-zA-Z]+)$"
)


def _safe_css_color(value) -> Optional[str]:
    """Return ``value`` if it is a safe CSS color for raw :root interpolation,
    else None. Guards the palette-to-CSS boundary against declaration-breakout
    injection while leaving every valid hex / rgb() / named color untouched."""
    if not isinstance(value, str):
        return None
    v = value.strip()
    return v if _SAFE_CSS_COLOR_RE.match(v) else None

# Neutral default palette for a tenant-supplied (BrandProfile) brand. Every key
# the shipped skeletons consume via var(--brand-*) is filled so the chosen layout
# renders correctly regardless of which keys the tenant provided. primary /
# secondary are overridden from the profile when valid; the rest are sensible
# theme-agnostic neutrals (a clean ink-on-white treatment that suits dark_band).
_PROFILE_DEFAULT_PALETTE: dict[str, str] = {
    "primary":       "#2563eb",   # blue-600 — accent (rules, kickers, KPI numbers)
    "primary_light": "#93c5fd",   # blue-300 — accent on dark surfaces
    "secondary":     "#0ea5e9",   # sky-500 — secondary accent (chips, glows)
    "accent":        "#eef2ff",   # very-light wash — subject-row highlight
    "ink":           "#0a0f1a",   # near-black — mast / verdict / footer surfaces
    "paper":         "#ffffff",   # clean white page
    "band":          "#f4f6fb",   # barely-there zebra stripe
    "rule":          "#e2e6ee",   # cool hairline borders
    "muted":         "#7a8699",   # muted slate labels / secondary text
    "slate":         "#33404f",   # tertiary text
    "good":          "#059669",   # emerald success
    "flag":          "#e11d48",   # rose — negative deltas / warnings
}

# Typography defaults for a profile-built brand — the shipped house defaults
# (Inter body + Instrument Serif display), so a tenant brand reads consistently
# with the rest of the product without requiring the tenant to pick fonts.
_PROFILE_DEFAULT_TYPOGRAPHY: dict[str, str] = {
    "body_family": "'Inter','Helvetica Neue',Arial,system-ui,sans-serif",
    "display_family": "'Instrument Serif',Georgia,'Times New Roman',serif",
    "google_fonts_url": (
        "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700"
        "&family=Instrument+Serif:ital@0;1&display=swap"
    ),
}

_SUPPORTED_LAYOUT_STYLES = ("dark_band", "cream_serif")
_DEFAULT_LAYOUT_STYLE = "dark_band"


def _valid_hex(value) -> Optional[str]:
    """Return ``value`` if it's a valid #RGB/#RRGGBB hex color, else None."""
    if not isinstance(value, str):
        return None
    v = value.strip()
    return v if _HEX_RE.match(v) else None


@dataclass
class AgentIdentity:
    """Per-CMA agent identity. Overrides the brand's default agent."""

    name: str = ""
    license: str = ""
    brokerage: str = ""
    jurisdiction: str = "Commonwealth of Virginia"

    @classmethod
    def from_dict(cls, data: dict) -> "AgentIdentity":
        return cls(
            name=data.get("name", ""),
            license=data.get("license", ""),
            brokerage=data.get("brokerage", ""),
            jurisdiction=data.get("jurisdiction", "Commonwealth of Virginia"),
        )

    def signature_html(self) -> str:
        """Render the agent signature line shown in the report footer.

        Every agent-controlled field (name, jurisdiction, brokerage) is
        HTML-escaped at this boundary — the values come from the tenant's saved
        BrandProfile and must not be able to inject markup into the render host.
        """
        line2_bits = ["Licensed Real Estate Agent"]
        if self.jurisdiction:
            line2_bits.append(_esc(self.jurisdiction))
        if self.brokerage:
            line2_bits.append(_esc(self.brokerage))
        line2 = " · ".join(line2_bits)
        name = _esc(self.name or "Licensed Agent")
        return f'<strong>{name}</strong>{line2}'


@dataclass
class Brand:
    """A white-label brand profile loaded from ``config/brands/<name>.yaml``.

    Construct via :meth:`Brand.load` rather than directly.
    """

    name: str
    display_name: str
    layout_style: str
    palette: dict[str, str]
    typography: dict[str, str]
    wordmark: str = ""
    tagline: str = ""
    logo_path: str = ""
    agent: AgentIdentity = field(default_factory=AgentIdentity)
    disclaimer: str = ""
    disclaimer_short: str = ""
    _project_root: Path = field(default_factory=lambda: _PROJECT_ROOT, repr=False)

    @classmethod
    def load(cls, name: str, brands_dir: Optional[Path] = None) -> "Brand":
        """Load a brand profile by name from disk."""
        brands_dir = Path(brands_dir) if brands_dir else _DEFAULT_BRANDS_DIR
        path = brands_dir / f"{name}.yaml"
        if not path.exists():
            available = sorted(p.stem for p in brands_dir.glob("*.yaml"))
            raise FileNotFoundError(
                f"Brand '{name}' not found at {path}. "
                f"Available brands: {available}"
            )
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls(
            name=data["name"],
            display_name=data.get("display_name", data["name"]),
            layout_style=data["layout_style"],
            palette=dict(data.get("palette", {})),
            typography=dict(data.get("typography", {})),
            wordmark=data.get("wordmark", ""),
            tagline=data.get("tagline", ""),
            logo_path=data.get("logo_path", ""),
            agent=AgentIdentity.from_dict(data.get("agent", {})),
            disclaimer=data.get("disclaimer", ""),
            disclaimer_short=data.get("disclaimer_short", ""),
        )

    @classmethod
    def from_profile(cls, profile: dict) -> "Brand":
        """Build a :class:`Brand` from a saved tenant BrandProfile dict.

        This lets the app render a tenant's OWN brand without a disk YAML file.
        It produces a Brand that renders through the SAME skeletons as the YAML
        brands — only the brand/theming tokens differ, never the report
        structure or valuation math.

        Accepted keys (all optional):
          - ``company_name`` / ``wordmark`` — sets ``display_name`` + ``wordmark``
          - ``primary_color``   — ``palette.primary``   (hex; validated)
          - ``secondary_color`` — ``palette.secondary`` (hex; validated)
          - ``logo_path``       — ``logo_path`` (raster lockup for dark_band)
          - ``disclaimer``      — ``disclaimer`` (and ``disclaimer_short`` if
                                  the latter is not separately supplied)
          - ``disclaimer_short``— ``disclaimer_short``
          - ``agent_name``      — agent identity name
          - ``license``         — agent identity license
          - ``tagline``         — ``tagline``
          - ``layout_style``    — one of ``dark_band`` (default) / ``cream_serif``

        Every other palette key the skeletons need (ink, paper, band, rule,
        muted, slate, good, flag, accent, primary_light) is filled from a neutral
        default palette so the chosen skeleton always renders. Invalid or missing
        hex colors fall back to the neutral defaults. Typography uses the house
        defaults (Inter + Instrument Serif).

        Robust by design: this method never raises on bad input — it coerces /
        defaults each field. ``build_cma`` additionally wraps the call so any
        unexpected failure falls back to the YAML-brand path.
        """
        profile = profile or {}

        # Identity: company_name is the canonical source; wordmark may override
        # the lockup text independently. Fall back across both.
        company_name = str(profile.get("company_name") or "").strip()
        wordmark_raw = str(profile.get("wordmark") or "").strip()
        display_name = company_name or wordmark_raw or "Custom Brand"
        wordmark = wordmark_raw or company_name or display_name

        # Layout style — only honor a supported style; otherwise default safely.
        layout_style = str(profile.get("layout_style") or "").strip()
        if layout_style not in _SUPPORTED_LAYOUT_STYLES:
            layout_style = _DEFAULT_LAYOUT_STYLE

        # Palette: start from the neutral defaults (fills EVERY key the skeletons
        # need), then overlay the validated tenant primary/secondary.
        palette = dict(_PROFILE_DEFAULT_PALETTE)
        primary = _valid_hex(profile.get("primary_color"))
        if primary:
            palette["primary"] = primary
        secondary = _valid_hex(profile.get("secondary_color"))
        if secondary:
            palette["secondary"] = secondary

        # Disclaimer: use a single supplied disclaimer for both long + short when
        # a distinct short form isn't given, so the footer always has copy.
        disclaimer = str(profile.get("disclaimer") or "").strip()
        disclaimer_short = str(profile.get("disclaimer_short") or "").strip()
        if disclaimer and not disclaimer_short:
            disclaimer_short = disclaimer

        agent = AgentIdentity(
            name=str(profile.get("agent_name") or "").strip(),
            license=str(profile.get("license") or "").strip(),
            jurisdiction="Commonwealth of Virginia",
        )

        # Account-unique brand name so two white-label tenants pricing the SAME
        # address never collide on one physical output file (the engine writes
        # CMA_<name>_<slug>.pdf to a shared outputs/ volume). The app passes
        # account_token=accountId; sanitized to a bare alnum token here.
        _tok = "".join(c for c in str(profile.get("account_token") or "").lower() if c.isalnum())[:24]
        return cls(
            name=("profile" + _tok) if _tok else "profile",
            display_name=display_name,
            layout_style=layout_style,
            palette=palette,
            typography=dict(_PROFILE_DEFAULT_TYPOGRAPHY),
            wordmark=wordmark,
            tagline=str(profile.get("tagline") or "").strip(),
            logo_path=str(profile.get("logo_path") or "").strip(),
            agent=agent,
            disclaimer=disclaimer,
            disclaimer_short=disclaimer_short,
        )

    # ----- CSS composition -----------------------------------------------

    def css_root_block(self) -> str:
        """Return the ``:root{}`` CSS block that exports brand tokens.

        Tokens are exposed under ``--brand-*`` for palette and
        ``--type-*`` for typography. The brand-token namespace lets a
        single skeleton stylesheet drive any brand.
        """
        lines = [":root{"]
        for key, value in self.palette.items():
            safe = _safe_css_color(value)
            if safe is None:
                # Drop an unsafe/garbage color rather than break out of the CSS
                # declaration; the skeleton's own fallback color then applies.
                continue
            css_key = key.replace("_", "-")
            lines.append(f"  --brand-{css_key}:{safe};")
        # Typography custom properties
        body = self.typography.get("body_family", "system-ui,sans-serif")
        display = self.typography.get("display_family", "serif")
        lines.append(f"  --type-body:{body};")
        lines.append(f"  --type-display:{display};")
        lines.append("}")
        return "\n".join(lines)

    def font_import(self) -> str:
        """Return a CSS @import for the brand's Google Fonts URL, or empty."""
        url = self.typography.get("google_fonts_url", "")
        return f"@import url('{url}');\n" if url else ""

    def print_css(self) -> str:
        """Return the full CSS string ready for embedding in an HTML report.

        Composition:
          @import + :root{} + skeleton[layout_style]
        """
        # Imported lazily to avoid a circular import with the skeleton module
        # at package init time and to keep brand.py free of Python-path tricks.
        from .skeletons import get_skeleton

        return "\n".join(
            [
                self.font_import().rstrip(),
                self.css_root_block(),
                get_skeleton(self.layout_style),
            ]
        ).strip() + "\n"

    # ----- Asset helpers -------------------------------------------------

    def logo_data_uri(self) -> str:
        """Return a ``data:image/...;base64,...`` URI for the brand logo.

        Falls back to an empty string if no ``logo_path`` is configured or the
        file cannot be read. Layouts that do not need a raster logo (e.g.
        ``cream_serif``) simply ignore the empty value.
        """
        if not self.logo_path:
            return ""
        candidate = Path(self.logo_path)
        if not candidate.is_absolute():
            candidate = self._project_root / self.logo_path
        if not candidate.exists():
            return ""
        suffix = candidate.suffix.lower().lstrip(".")
        mime = {"png": "png", "jpg": "jpeg", "jpeg": "jpeg", "svg": "svg+xml"}.get(
            suffix, "octet-stream"
        )
        encoded = base64.b64encode(candidate.read_bytes()).decode()
        return f"data:image/{mime};base64,{encoded}"

    # ----- Layout-aware HTML helpers ------------------------------------

    def masthead_html(self, docmeta_rows: list[tuple[str, str]]) -> str:
        """Render the masthead block appropriate for this brand's layout style.

        ``docmeta_rows`` is a list of ``(label, value)`` tuples shown on the
        right of the masthead — e.g. ``[("Prepared", "June 9, 2026"), ...]``.
        """
        rows_html = "".join(
            f'<div><strong>{_esc(label)}</strong> {_esc(value)}</div>' for label, value in docmeta_rows
        )
        if self.layout_style == "dark_band":
            uri = self.logo_data_uri()
            logo = (
                f'<img class="lockup-img" src="{uri}" alt="{_esc(self.display_name)}" />'
                if uri
                else f'<div class="lockup-text">{_esc(self.wordmark)}</div>'
            )
            return (
                '<div class="masthead"><div class="mastbar">'
                f"{logo}"
                f'<div class="docmeta">{rows_html}</div>'
                "</div></div>"
            )
        if self.layout_style == "cream_serif":
            return (
                '<div class="masthead">'
                '<div class="brand">'
                f'<div class="wordmark">{_esc(self.wordmark)}</div>'
                f'<div class="tag">{_esc(self.tagline)}</div>'
                "</div>"
                f'<div class="docmeta">{rows_html}</div>'
                "</div>"
            )
        raise ValueError(f"Unknown layout_style: {self.layout_style!r}")

    def footer_brand_html(self) -> str:
        """Render the footer-brand block (right side of the footer signature row)."""
        if self.layout_style == "dark_band":
            uri = self.logo_data_uri()
            return (
                f'<img class="foot-lockup" src="{uri}" alt="{_esc(self.display_name)}" />'
                if uri
                else f'<div class="foot-wordmark">{_esc(self.wordmark)}</div>'
            )
        if self.layout_style == "cream_serif":
            return (
                '<div class="foot-brand">'
                f'<div class="wm">{_esc(self.wordmark)}</div>'
                f'<div class="wt">{_esc(self.tagline)}</div>'
                "</div>"
            )
        raise ValueError(f"Unknown layout_style: {self.layout_style!r}")

    def footer_html(self, agent: Optional[AgentIdentity] = None,
                    use_short_disclaimer: bool = False) -> str:
        """Render the complete footer block (signature row + disclaimer)."""
        agent = agent or self.agent
        disc = self.disclaimer_short if use_short_disclaimer else self.disclaimer
        return (
            '<div class="foot">'
            '<div class="sig">'
            f'<div class="who">{agent.signature_html()}</div>'
            f"{self.footer_brand_html()}"
            "</div>"
            f'<div class="disc">{_esc(disc)}</div>'
            "</div>"
        )


def available_brands(brands_dir: Optional[Path] = None) -> list[str]:
    """Return the sorted list of brand names installed under ``config/brands/``."""
    brands_dir = Path(brands_dir) if brands_dir else _DEFAULT_BRANDS_DIR
    if not brands_dir.exists():
        return []
    return sorted(p.stem for p in brands_dir.glob("*.yaml"))

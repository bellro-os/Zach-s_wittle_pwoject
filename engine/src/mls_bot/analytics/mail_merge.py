"""Personalized mail-merge — generate per-prospect letters from seller_scores.csv.

Reads the top-N rows of outputs/mls_analytics/leads/seller_scores.csv, runs the
AVM for each prospect to estimate current value, computes equity gain since
last sale, then renders a personalized HTML letter using one of four themed
templates. Each letter gets a unique tracking ID and a QR code linking to the
prospect's personalized landing page.

Output:
    outputs/mls_analytics/mail_merge/<batch>/<tracking_id>.html
    outputs/mls_analytics/mail_merge/<batch>/<tracking_id>.pdf   (if Edge present)
    outputs/mls_analytics/mail_merge/<batch>/index.csv

The batch dir is named "<theme>_YYYYMMDD". Re-running the same theme on the
same day overwrites that batch.

Themes:
    equity_pitch   — high estimated equity vs last sale price
    tenure_pitch   — long-tenure owners (10+ years)
    expired_relist — owners whose listings recently expired
    estate_pitch   — estate / trust / heirs / trustee owners
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import re
from datetime import date, datetime
from pathlib import Path

from .cma import _load_agent_card, render_pdf


SCORES_CSV = Path("outputs/mls_analytics/leads/seller_scores.csv")
TEMPLATES_DIR = Path("templates")
OUT_ROOT = Path("outputs/mls_analytics/mail_merge")

THEMES = ("equity_pitch", "tenure_pitch", "expired_relist", "estate_pitch")


# ---------- helpers ---------------------------------------------------------

def _fmt_money(v) -> str:
    if v in (None, "", "None"):
        return ""
    try:
        return f"${float(v):,.0f}"
    except (TypeError, ValueError):
        return str(v)


def _tracking_id(parcel_id: str, county: str, theme: str) -> str:
    """Deterministic 6-char tracking code: 'Z' + 5 hex chars."""
    h = hashlib.sha1(f"{parcel_id}|{county}|{theme}".encode("utf-8")).hexdigest()
    return ("Z" + h[:5]).upper()


def _owner_first(owner: str) -> str:
    """Best-effort first-name extraction from a county owner string.
    Falls back to 'Neighbor' if we can't safely guess."""
    if not owner:
        return "Neighbor"
    o = owner.strip()
    # Trust / estate / LLC patterns
    if re.search(r"\b(TRUST|ESTATE|LLC|INC|CORP|LP|LTD|TRUSTEE|EXECUTOR)\b", o, re.I):
        return "Property Owner"
    # Multi-owner: "SMITH JOHN & JANE" or "SMITH, JOHN"
    parts = re.split(r"[,&]| AND ", o)
    first_chunk = parts[0].strip()
    tokens = first_chunk.split()
    if len(tokens) >= 2:
        # County records are usually LAST FIRST [MIDDLE]
        candidate = tokens[1]
        if len(candidate) >= 2 and candidate.isalpha():
            return candidate.title()
    return "Neighbor"


def _qr_data_uri(payload: str) -> str:
    """Generate a QR code as a base64 PNG data URI."""
    try:
        import qrcode
    except ImportError:
        return ""
    qr = qrcode.QRCode(box_size=4, border=2)
    qr.add_data(payload or "")
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _render_template(template_path: Path, fields: dict) -> str:
    """Trivial {{var}} substitution. Missing keys render as empty string."""
    text = template_path.read_text(encoding="utf-8")

    def _sub(m):
        key = m.group(1).strip()
        return str(fields.get(key, ""))

    return re.sub(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}", _sub, text)


# ---------- prospect filtering ---------------------------------------------

def _filter_for_theme(rows: list[dict], theme: str) -> list[dict]:
    """Pick rows that are a good fit for the chosen theme."""
    out = []
    for r in rows:
        signals = (r.get("signals_pos") or "").lower()
        try:
            tenure = float(r.get("tenure_years") or 0)
        except ValueError:
            tenure = 0.0
        try:
            equity = float(r.get("estimated_equity") or 0)
        except ValueError:
            equity = 0.0

        if theme == "equity_pitch":
            # Positive equity OR long-tenure-with-purchase data is fine; this is the
            # general-purpose pitch and casts the widest net.
            if equity > 50_000 or tenure >= 5:
                out.append(r)
        elif theme == "tenure_pitch":
            if tenure >= 10:
                out.append(r)
        elif theme == "expired_relist":
            if "expired:" in signals:
                out.append(r)
        elif theme == "estate_pitch":
            if "estate_pattern" in signals or re.search(
                r"\b(TRUST|ESTATE|TRUSTEE|EXECUTOR|HEIRS)\b",
                (r.get("owner") or ""), re.I
            ):
                out.append(r)
        else:
            out.append(r)
    return out


# ---------- main ------------------------------------------------------------

def generate_letters(
    *,
    theme: str = "equity_pitch",
    score_min: int = 60,
    max_n: int = 100,
    base_url: str = "",
    skip_recently_contacted: bool = True,
    render_pdfs: bool = True,
    campaign: str | None = None,
) -> dict:
    """Generate a batch of personalized letters.

    base_url: hostname + prefix where landing pages will be served, e.g.
        "https://zachstotz.example.com/h/" — the QR code points to
        "{base_url}{tracking_id}". If empty, points to a relative path
        "landing/<tracking_id>.html" which works for local file:// access.
    """
    if theme not in THEMES:
        raise ValueError(f"theme must be one of {THEMES}, got {theme!r}")
    if not SCORES_CSV.exists():
        raise FileNotFoundError(f"{SCORES_CSV} not found — run mls-seller-scores first")
    template_path = TEMPLATES_DIR / f"letter_{theme}.html"
    if not template_path.exists():
        raise FileNotFoundError(f"missing template: {template_path}")

    # Load prospects
    with SCORES_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        all_rows = list(csv.DictReader(f))
    rows = []
    for r in all_rows:
        try:
            sc = int(float(r.get("score") or 0))
        except ValueError:
            sc = 0
        if sc < score_min:
            continue
        status = (r.get("outreach_status") or "").lower()
        if skip_recently_contacted and status.startswith("contacted_"):
            continue
        if skip_recently_contacted and status == "cold":
            continue
        # Skip flipper-pattern entities — they're buyers, not listing prospects
        if str(r.get("is_flipper_pattern", "")).lower() == "true":
            continue
        rows.append(r)
    rows = _filter_for_theme(rows, theme)
    rows = rows[:max_n]
    if not rows:
        return {"theme": theme, "n": 0, "batch_dir": None, "msg": "no prospects matched filter"}

    # Default campaign tag
    if campaign is None:
        campaign = f"{theme}_{date.today().strftime('%Y%m')}"

    # Output dir
    batch_id = f"{theme}_{date.today().isoformat().replace('-', '')}"
    batch_dir = OUT_ROOT / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)

    agent = (_load_agent_card() or {}).get("agent") or {}
    agent_fields = {
        "agent_name": agent.get("name", ""),
        "agent_brokerage": agent.get("brokerage", ""),
        "agent_phone": agent.get("phone", ""),
        "agent_email": agent.get("email", ""),
    }
    today_long = date.today().strftime("%B %d, %Y")

    # Lazy AVM import (joblib model load is heavy)
    try:
        from .avm import predict_for_parcel
    except Exception as e:
        print(f"  [mail_merge] AVM unavailable: {e}")
        predict_for_parcel = None  # type: ignore

    index_rows = []
    n_pdf = 0
    n_html = 0
    for r in rows:
        parcel_id = (r.get("parcel_id") or "").strip()
        county = (r.get("county") or "").strip().upper()
        owner = (r.get("owner") or "").strip()
        site_addr = (r.get("site_addr") or "").strip()
        mail_addr = (r.get("mail_addr") or "").strip()
        subdivision = (r.get("subdivision") or "").strip()
        year_built = (r.get("year_built") or "").strip()
        last_sale_date = (r.get("last_sale_date") or "").strip()
        last_sale_price = (r.get("last_sale_price") or "").strip()
        try:
            tenure_years = float(r.get("tenure_years") or 0)
        except ValueError:
            tenure_years = 0.0
        try:
            assessed = float(r.get("assessed_total") or 0)
        except ValueError:
            assessed = 0.0
        signals = (r.get("signals_pos") or "")

        # AVM lookup (fall back to assessed if MLS-blank)
        avm_val: float | None = None
        if predict_for_parcel and parcel_id:
            try:
                pred = predict_for_parcel(parcel_id)
                avm_val = pred.get("predicted_value") if pred else None
            except Exception:
                avm_val = None
        if not avm_val and assessed:
            avm_val = assessed * 1.15  # rough assessed→market bump for VA

        # Equity gain
        try:
            last_price = float(last_sale_price) if last_sale_price else 0.0
        except ValueError:
            last_price = 0.0
        equity_gain = (avm_val - last_price) if (avm_val and last_price) else None

        purchase_year = last_sale_date[:4] if last_sale_date else ""
        if last_price > 0:
            purchase_price_clause = f" for {_fmt_money(last_price)}"
        else:
            purchase_price_clause = ""

        if equity_gain and equity_gain > 0:
            equity_gain_line = (
                f"That's roughly <strong>{_fmt_money(equity_gain)}</strong> in appreciation"
                + (f" over {tenure_years:.0f} years." if tenure_years >= 1 else ".")
            )
        elif tenure_years >= 1:
            equity_gain_line = f"You've held it for {tenure_years:.0f} years."
        else:
            equity_gain_line = ""

        # Rough cohort phrasing
        inventory_phrase = "tight in your price range"
        cohort_dom = "30–45"

        # Expired-listing context line
        m = re.search(r"expired:(\d{4}-\d{2}-\d{2})", signals)
        if m:
            expired_context_line = f"The MLS shows your prior listing expired {m.group(1)}."
        else:
            expired_context_line = ""

        if last_sale_date and last_price:
            purchase_summary_line = (
                f"Last deeded transfer: {last_sale_date} for {_fmt_money(last_price)}."
            )
        elif last_sale_date:
            purchase_summary_line = f"Last deeded transfer: {last_sale_date}."
        else:
            purchase_summary_line = ""

        tracking_id = _tracking_id(parcel_id, county, theme)
        if base_url:
            landing_url = base_url.rstrip("/") + "/" + tracking_id
        else:
            landing_url = f"landing/{tracking_id}.html"
        qr_uri = _qr_data_uri(landing_url)

        owner_first = _owner_first(owner)
        owner_short = owner.split(",")[0].split("&")[0].strip().title() or "the owner(s)"

        fields = {
            **agent_fields,
            "today_long": today_long,
            "owner": owner.title(),
            "owner_first": owner_first,
            "owner_short": owner_short,
            "site_addr": site_addr.title(),
            "mail_addr": mail_addr.title(),
            "subdivision_or_city": subdivision.title() if subdivision else "your area",
            "city": (subdivision or county.title()),
            "purchase_year": purchase_year,
            "purchase_price_clause": purchase_price_clause,
            "purchase_summary_line": purchase_summary_line,
            "tenure_years": f"{tenure_years:.0f}" if tenure_years else "",
            "year_built": year_built,
            "avm_value": _fmt_money(avm_val) or "(estimate available on request)",
            "equity_gain_line": equity_gain_line,
            "expired_context_line": expired_context_line,
            "inventory_phrase": inventory_phrase,
            "cohort_dom": cohort_dom,
            "tracking_id": tracking_id,
            "landing_url": landing_url,
            "qr_data_uri": qr_uri,
        }

        html = _render_template(template_path, fields)
        html_path = batch_dir / f"{tracking_id}.html"
        html_path.write_text(html, encoding="utf-8")
        n_html += 1

        # Render the matching landing page (one per prospect)
        try:
            from .landing_page import render_landing_page
            render_landing_page(
                tracking_id=tracking_id,
                parcel_id=parcel_id,
                site_addr=site_addr,
                owner_first=owner_first,
                avm_value=avm_val,
                last_sale_date=last_sale_date,
                last_sale_price=last_price if last_price else None,
                tenure_years=tenure_years,
                equity_gain=equity_gain,
            )
        except Exception as e:
            print(f"  [mail_merge] landing page failed for {tracking_id}: {e}")

        pdf_path = None
        if render_pdfs:
            pdf_path = render_pdf(html_path)
            if pdf_path:
                n_pdf += 1

        index_rows.append({
            "tracking_id": tracking_id,
            "theme": theme,
            "campaign": campaign,
            "parcel_id": parcel_id,
            "county": county,
            "owner": owner,
            "site_addr": site_addr,
            "mail_addr": mail_addr,
            "score": r.get("score", ""),
            "tenure_years": r.get("tenure_years", ""),
            "last_sale_date": last_sale_date,
            "last_sale_price": last_sale_price,
            "avm_value": int(avm_val) if avm_val else "",
            "equity_gain": int(equity_gain) if equity_gain else "",
            "landing_url": landing_url,
            "html": str(html_path),
            "pdf": str(pdf_path) if pdf_path else "",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        })

    # Index CSV
    index_csv = batch_dir / "index.csv"
    if index_rows:
        with index_csv.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(index_rows[0].keys()))
            w.writeheader()
            for ir in index_rows:
                w.writerow(ir)

    return {
        "theme": theme,
        "batch_id": batch_id,
        "batch_dir": str(batch_dir),
        "n": len(index_rows),
        "n_html": n_html,
        "n_pdf": n_pdf,
        "index_csv": str(index_csv),
    }

"""Pre-meeting CMA send — generate a CMA + email it to the seller 24 hours
before a listing-presentation meeting.

The seller arrives prepared with the comp set, the recommended price, and the
listing-strategy block. By the time you walk in, they're not asking "what's it
worth?" — they're asking "how do we execute the plan?"

CLI:
    python tasks.py mls-pre-meeting --parcel-id 023337 --email seller@example.com --meeting-date 2026-05-20

Reuses cma_for() + render_html() + render_pdf() and the existing SMTP config
in .env.
"""

from __future__ import annotations

import smtplib
from datetime import date, datetime
from email.message import EmailMessage
from pathlib import Path

from .cma import cma_for, render_html, render_pdf, _load_agent_card


PRE_MEETING_DIR = Path("outputs/mls_analytics/pre_meeting")


def _smtp_settings() -> dict:
    """Pull SMTP creds from the project's settings module."""
    try:
        from ..config import load as _load
        s = _load()
        return {
            "host": s.smtp_host, "port": s.smtp_port,
            "user": s.smtp_user, "password": s.smtp_pass,
            "from_addr": s.digest_from or s.smtp_user,
        }
    except Exception:
        import os
        return {
            "host": os.getenv("SMTP_HOST", "smtp.gmail.com"),
            "port": int(os.getenv("SMTP_PORT", "587")),
            "user": os.getenv("SMTP_USER", ""),
            "password": os.getenv("SMTP_PASS", ""),
            "from_addr": os.getenv("DIGEST_FROM", "") or os.getenv("SMTP_USER", ""),
        }


def _build_email_body(report: dict, meeting_date: str, *, agent: dict) -> str:
    """Plain-text email body. Concise — the CMA PDF is the substance."""
    s = report.get("subject") or {}
    strat = report.get("listing_strategy") or {}
    rp = strat.get("recommended_price")

    def _money(v) -> str:
        if v in (None, "", "None"):
            return "—"
        try:
            return f"${float(v):,.0f}"
        except (TypeError, ValueError):
            return str(v)

    addr = s.get("address") or "your property"
    lines = [
        f"Hi —",
        "",
        f"Quick prep ahead of our meeting on {meeting_date} about {addr}.",
        "",
        "Attached: a full CMA (PDF) covering the cohort, recent comps,",
        "and a recommended listing strategy. Three things to glance at",
        "before we sit down:",
        "",
        f"  1. Recommended list price: {_money(rp)}",
        f"  2. Expected days on market: {strat.get('expected_dom_range','—')}",
    ]
    risks = strat.get("risk_items") or []
    if risks:
        lines.append("  3. Risk items I want to walk through:")
        for r in risks[:3]:
            lines.append(f"     - {r}")
    lines += [
        "",
        "If anything in the analysis looks off — pricing too aggressive, a",
        "comp that doesn't fit, condition assumptions you'd dispute — bring",
        "it up first thing and we'll re-cut the numbers.",
        "",
        "See you then,",
        agent.get("name", ""),
        agent.get("brokerage", ""),
        f"{agent.get('phone','')}{(' · ' + agent.get('email','')) if agent.get('email') else ''}",
    ]
    return "\n".join(lines)


def send_pre_meeting_cma(
    *,
    parcel_id: str | None = None,
    address: str | None = None,
    city: str | None = None,
    proposed_price: float | None = None,
    seller_email: str,
    meeting_date: str,
    dry_run: bool = False,
) -> dict:
    """Generate a CMA and (optionally) email it to the seller.

    proposed_price: if not provided, falls back to the listing's MLS list_price
    or to deed_last_sale_price. Required only if both are missing.

    dry_run=True writes the artifacts to disk but does not send the email.
    """
    if not (parcel_id or address):
        raise ValueError("must supply parcel_id or address")
    if not seller_email:
        raise ValueError("seller_email is required")

    # Determine a proposed price for the CMA cohort logic
    if proposed_price is None:
        from .cma import find_subject
        s = find_subject(parcel_id=parcel_id, address=address, city=city)
        if not s:
            raise RuntimeError("subject not found in MLS data")
        try:
            proposed_price = (float(s.get("list_price") or 0) or
                               float(s.get("deed_last_sale_price") or 0) or
                               float(s.get("parcel_assessed_total") or 0) or 250_000)
        except (TypeError, ValueError):
            proposed_price = 250_000

    report = cma_for(
        parcel_id=parcel_id, address=address, city=city,
        proposed_price=proposed_price,
    )
    if "error" in report:
        raise RuntimeError(report["error"])

    PRE_MEETING_DIR.mkdir(parents=True, exist_ok=True)
    sid = parcel_id or (address or "subject").replace(" ", "_")[:30]
    sid = "".join(c if c.isalnum() or c in "-_" else "_" for c in sid)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    html_path = PRE_MEETING_DIR / f"{sid}_{ts}.html"
    render_html(report, html_path)
    pdf_path = render_pdf(html_path)

    agent = (_load_agent_card() or {}).get("agent") or {}
    body = _build_email_body(report, meeting_date, agent=agent)
    subject_addr = (report.get("subject") or {}).get("address") or "your property"
    subject = f"Quick prep for our {meeting_date} meeting on {subject_addr}"

    smtp = _smtp_settings()
    sent = False
    if not dry_run and smtp["user"] and smtp["password"]:
        msg = EmailMessage()
        msg["From"] = smtp["from_addr"] or smtp["user"]
        msg["To"] = seller_email
        msg["Subject"] = subject
        msg.set_content(body)
        if pdf_path and pdf_path.exists():
            msg.add_attachment(
                pdf_path.read_bytes(),
                maintype="application", subtype="pdf",
                filename=pdf_path.name,
            )
        with smtplib.SMTP(smtp["host"], smtp["port"]) as srv:
            srv.starttls()
            srv.login(smtp["user"], smtp["password"])
            srv.send_message(msg)
        sent = True

    return {
        "sent": sent,
        "dry_run": dry_run,
        "html": str(html_path),
        "pdf": str(pdf_path) if pdf_path else "",
        "to": seller_email,
        "subject": subject,
        "preview_body": body,
    }

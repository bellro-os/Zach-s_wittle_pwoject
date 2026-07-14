"""Daily digest email. Sends only NEW leads (first_seen_at >= today)."""

from __future__ import annotations

import smtplib
from email.mime.text import MIMEText
from datetime import date

from jinja2 import Template

from .config import load
from .db import connect


TEMPLATE = Template("""\
MLS Bot daily digest — {{ today }}

Expired / withdrawn listings ({{ expired|length }} new):
{% for l in expired %}
  - [{{ l.score }}]  {{ l.detail.site_addr }}  ({{ l.detail.city }})
      MLS #{{ l.detail.mls_number }}  |  status {{ l.detail.status }}
      list ${{ "{:,.0f}".format(l.detail.list_price) if l.detail.list_price else "?" }}
      DOM {{ l.detail.dom or "?" }}  |  changed {{ l.detail.status_changed_at }}
{% else %}
  (none)
{% endfor %}

High-equity absentee owners ({{ absentee|length }} new):
{% for l in absentee %}
  - [{{ l.score }}]  {{ l.detail.site_addr }}
      owner: {{ l.detail.owner1 }}{% if l.detail.owner2 %} / {{ l.detail.owner2 }}{% endif %}
      mails to: {{ l.detail.mail_addr }}
      assessed ${{ "{:,.0f}".format(l.detail.assessed_total) }}
      bought {{ l.detail.last_sale_date }} for ${{ "{:,.0f}".format(l.detail.last_sale_price) }}
      tenure {{ l.detail.tenure_years }}y  |  equity ~{{ (l.detail.equity_ratio * 100)|round(0) }}%
{% else %}
  (none)
{% endfor %}

Reminder: scrub the federal DNC list before calling any of these.
""")


SELECT_NEW = """
SELECT category, score, detail
FROM leads
WHERE category = %s
  AND first_seen_at::date = current_date
ORDER BY score DESC
LIMIT 50;
"""


def build() -> str:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(SELECT_NEW, ("EXPIRED",))
        expired = cur.fetchall()
        cur.execute(SELECT_NEW, ("ABSENTEE_HIGH_EQUITY",))
        absentee = cur.fetchall()
    return TEMPLATE.render(today=date.today().isoformat(), expired=expired, absentee=absentee)


def send() -> None:
    s = load()
    body = build()
    if not s.smtp_user or not s.digest_to:
        print(body)
        return
    msg = MIMEText(body)
    msg["Subject"] = f"MLS Bot — {date.today().isoformat()}"
    msg["From"] = s.digest_from or s.smtp_user
    msg["To"] = s.digest_to
    with smtplib.SMTP(s.smtp_host, s.smtp_port) as srv:
        srv.starttls()
        srv.login(s.smtp_user, s.smtp_pass)
        srv.send_message(msg)

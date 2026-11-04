"""Builds the Hebrew digest email and sends it to you (or saves it, in DRY_RUN)."""
import html
import mimetypes
import smtplib
from datetime import date
from email.message import EmailMessage
from pathlib import Path

import config


def _job_block(job: dict) -> str:
    fit = job.get("fit_json") or {}
    co = job.get("company_json") or {}
    e = html.escape
    gaps = "".join(f"<li>{e(g)}</li>" for g in fit.get("gaps", []))
    points = "".join(f"<li>{e(p)}</li>" for p in co.get("talking_points", [])[:3])
    return f"""
    <div style="border:1px solid #ddd;border-radius:8px;padding:12px;margin:12px 0">
      <h3 style="margin:0">{e(job['title'])} — {e(job['company'])}</h3>
      <p style="margin:4px 0;color:#555">{e(job.get('location') or '')} | התאמה: {job.get('fit_score')}/10</p>
      <p><a href="{e(job.get('url') or '#')}">למודעה</a>
         {f' | <a href="{e(co["official_apply_url"])}">הגשה באתר החברה</a>' if co.get('official_apply_url') else ''}</p>
      <p><b>למה מתאים:</b> {e(fit.get('one_line', ''))}</p>
      {f'<p><b>פערים:</b></p><ul>{gaps}</ul>' if gaps else ''}
      <p><b>על החברה:</b> {e(co.get('what_they_do', ''))}</p>
      {f'<p><b>מה להזכיר:</b></p><ul>{points}</ul>' if points else ''}
      <p><b>מכתב פנייה:</b></p>
      <p dir="ltr" style="white-space:pre-wrap;background:#f7f7f7;padding:8px">{e(job.get('cover_md') or '')}</p>
      <p>📎 קו"ח מותאמים מצורפים: {e(Path(job['cv_path']).name)}</p>
    </div>"""


def build_message(jobs: list[dict]) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = f"משרות להיום — {date.today():%d/%m/%Y} ({len(jobs)} משרות)"
    msg["From"] = config.GMAIL_ADDRESS or "job-agents@localhost"
    msg["To"] = config.MY_EMAIL or "me@localhost"
    body = "".join(_job_block(j) for j in jobs)
    msg.set_content("הגרסה המלאה של המייל היא HTML.")
    msg.add_alternative(
        f'<div dir="rtl" style="font-family:Arial,sans-serif">'
        f"<h2>נמצאו {len(jobs)} משרות מתאימות</h2>{body}"
        f'<p style="color:#888">לא נשלח שום דבר לחברות. ההגשה בידיים שלך.</p></div>',
        subtype="html",
    )
    for job in jobs:
        p = Path(job["cv_path"])
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        maintype, subtype = ctype.split("/", 1)
        msg.add_attachment(p.read_bytes(), maintype=maintype, subtype=subtype, filename=p.name)
    return msg


def send_digest(jobs: list[dict]) -> str:
    msg = build_message(jobs)
    if config.DRY_RUN:
        out = config.OUTBOX / f"digest_{date.today()}.eml"
        out.write_bytes(bytes(msg))
        return f"saved to {out} (DRY_RUN - not sent)"
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(config.GMAIL_ADDRESS, config.GMAIL_APP_PASSWORD)
        smtp.send_message(msg)
    return f"sent to {config.MY_EMAIL}"

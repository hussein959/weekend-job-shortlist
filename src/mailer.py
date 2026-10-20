"""Build and send the shortlist email over SMTP (Gmail by default)."""
from __future__ import annotations

import html
import mimetypes
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path
from typing import List, Tuple

from .common import Job, env

e = html.escape


def _card(i: int, job: Job, cv_file: str, warnings: List[str], notes: str) -> str:
    m = job.match
    gaps = ", ".join(m.get("gaps") or []) or "None significant"
    warn = ""
    if warnings:
        items = "".join(f"<li>{e(w)}</li>" for w in warnings[:8])
        warn = f'<p style="margin:8px 0 0;color:#8a5a00;font-size:12px"><b>Fact-check notes (review before sending):</b></p><ul style="margin:2px 0;color:#8a5a00;font-size:12px">{items}</ul>'
    salary = f" · {e(job.salary)}" if job.salary else ""
    return f"""
<div style="border:1px solid #dde3ea;border-radius:8px;padding:14px 16px;margin:0 0 14px">
  <div style="font-size:16px;font-weight:600;color:#1f3a5f">{i}. {e(job.title)}</div>
  <div style="color:#333;margin:2px 0 8px"><b>{e(job.company)}</b> · {e(job.location)}{salary}</div>
  <div style="font-size:13px;margin-bottom:8px">
    <span style="background:#e6f4ea;color:#1e6b34;padding:2px 8px;border-radius:10px"><b>{e(str(m.get('score')))}%</b> match</span>
    <span style="color:#666"> · {int(m.get('requirement_ratio', 0) * 100)}% of requirements met · seniority: {e(str(m.get('seniority_fit')))} · source: {e(job.source)}</span>
  </div>
  <p style="margin:6px 0"><b>Why you match:</b> {e(m.get('why_match', ''))}</p>
  <p style="margin:6px 0"><b>Gaps:</b> {e(gaps)}</p>
  <p style="margin:6px 0"><b>Location:</b> {e(m.get('location_note', ''))}</p>
  <p style="margin:6px 0"><b>CV tailoring:</b> {e(notes)}</p>
  <p style="margin:6px 0"><b>Tailored CV:</b> attached as <code>{e(cv_file)}</code></p>
  <p style="margin:10px 0 0"><a href="{e(job.url)}" style="background:#1f3a5f;color:#fff;padding:7px 14px;border-radius:5px;text-decoration:none">Open job posting</a></p>
  {warn}
</div>"""


def _others(jobs: List[Job]) -> str:
    """Compact list of screened jobs that did not get a tailored CV."""
    rows = []
    for j in jobs:
        m = j.match
        gaps = ", ".join(m.get("gaps") or [])
        rows.append(f"""
<div style="border-top:1px solid #eee;padding:10px 0">
  <div><span style="display:inline-block;min-width:42px;font-weight:600;color:#1f3a5f">{e(str(m.get('score')))}%</span>
    <a href="{e(j.url)}" style="color:#1f3a5f;font-weight:600">{e(j.title)}</a> · {e(j.company)} · {e(j.location)}</div>
  <div style="font-size:13px;color:#444;margin:4px 0 0 42px">{e(m.get('why_match', ''))}</div>
  <div style="font-size:12px;color:#888;margin:2px 0 0 42px">Gaps: {e(gaps or 'none listed')} · {e(m.get('location_note', ''))}</div>
</div>""")
    return f"""<h3 style="color:#1f3a5f;margin:24px 0 4px">Other jobs screened ({len(jobs)})</h3>
<p style="color:#666;margin:0 0 6px;font-size:13px">Below the match bar, so no tailored CV. Sorted by score.</p>
{''.join(rows)}"""


def build_email(date: str, packages: List[Tuple[Job, Path, List[str], str]], stats: dict,
                others: List[Job] = ()) -> Tuple[str, str]:
    extra = stats["matches"] - len(packages)
    carry = f" ({extra} more carried over to the next run)" if extra > 0 else ""
    cards = "".join(_card(i, j, p.name, w, n) for i, (j, p, w, n) in enumerate(packages, 1))
    if not cards:
        cards = '<p>No roles passed the match threshold on this run. The search runs again next Saturday/Sunday.</p>'
    body = f"""<html><body style="font-family:Segoe UI,Arial,sans-serif;max-width:720px;margin:auto;color:#222">
<h2 style="color:#1f3a5f;margin-bottom:4px">Your job shortlist · {e(date)}</h2>
<p style="color:#666;margin-top:0">{e(stats['region'])} · {stats['fetched']} postings found · {stats['candidates']} screened in depth · {stats['matches']} strong matches · {len(packages)} tailored CVs below{carry}.
Each CV was tailored only from your master CV and fact-checked; please still read it before applying.</p>
{cards}
{_others(list(others)) if others else ""}
<p style="color:#999;font-size:12px">Generated automatically. Nothing has been submitted on your behalf.</p>
</body></html>"""
    text = "\n\n".join(
        f"{i}. {j.title} - {j.company} ({j.location})\nMatch: {j.match.get('score')}%\n{j.url}\nWhy: {j.match.get('why_match', '')}\nCV: {p.name}"
        for i, (j, p, _, _) in enumerate(packages, 1)
    ) or "No strong matches on this run."
    if others:
        text += "\n\nOther jobs screened:\n" + "\n".join(
            f"- {j.match.get('score')}% {j.title} - {j.company} ({j.location}) {j.url}" for j in others)
    return body, text


def send_email(subject: str, html_body: str, text_body: str, attachments: List[Path]) -> None:
    host = env("SMTP_HOST", "smtp.gmail.com")
    port = int(env("SMTP_PORT", "465"))
    user = env("SMTP_USER", required=True)
    password = env("SMTP_PASSWORD", required=True)
    to = env("EMAIL_TO", user)

    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, env("EMAIL_FROM", user), to
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    for path in attachments:
        ctype, _ = mimetypes.guess_type(path.name)
        maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
        msg.add_attachment(path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name)

    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx) as s:
            s.login(user, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port) as s:
            s.starttls(context=ctx)
            s.login(user, password)
            s.send_message(msg)

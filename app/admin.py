"""
Advisor overview: a password-protected list of conversations and leads.

Plain server-rendered HTML behind HTTP Basic auth, so advisors only need a
browser and the shared password. Disabled entirely unless ADMIN_PASSWORD is
set. Every value from the database is HTML-escaped, since transcripts
contain whatever visitors typed.

    ADMIN_USERNAME  (default "unlp")
    ADMIN_PASSWORD  required to enable /admin
"""

import os
import secrets
from html import escape
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.notify import STEP_LABELS
from app.storage import get_conversation_detail, list_conversations

router = APIRouter(prefix="/admin")
security = HTTPBasic(realm="Studiekompas")

PAGE_SIZE = 50
LOCAL_TZ = ZoneInfo("Europe/Amsterdam")


def require_advisor(credentials: HTTPBasicCredentials = Depends(security)) -> None:
    password = os.environ.get("ADMIN_PASSWORD")
    if not password:
        raise HTTPException(status_code=404)
    username = os.environ.get("ADMIN_USERNAME", "unlp")
    valid = secrets.compare_digest(credentials.username.encode(), username.encode()) & \
        secrets.compare_digest(credentials.password.encode(), password.encode())
    if not valid:
        raise HTTPException(status_code=401, headers={"WWW-Authenticate": 'Basic realm="Studiekompas"'})


def fmt_time(value) -> str:
    return value.astimezone(LOCAL_TZ).strftime("%d-%m-%Y %H:%M") if value else "-"


def page(title: str, body: str) -> HTMLResponse:
    html = f"""<!doctype html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{escape(title)}</title>
<style>
  :root {{ --bg:#FAF7F2; --ink:#26241F; --soft:#6B6558; --navy:#1B2A4D; --gold:#E3993D;
           --border:#E4DFD5; --card:#FFFFFF; --bot:#F1ECE2; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
         font:15px/1.5 -apple-system, BlinkMacSystemFont, 'Inter', sans-serif; }}
  header {{ background:var(--navy); color:#FAF7F2; padding:14px 16px; }}
  header a {{ color:#FAF7F2; text-decoration:none; font-weight:600; }}
  main {{ max-width:960px; margin:0 auto; padding:20px 16px 48px; }}
  h1 {{ font-size:20px; margin:0 0 12px; }}
  h2 {{ font-size:16px; margin:24px 0 8px; }}
  a {{ color:var(--navy); }}
  .filters a {{ margin-right:12px; }}
  .filters a.active {{ font-weight:700; text-decoration:none; }}
  .card {{ background:var(--card); border:1px solid var(--border); border-radius:10px;
          padding:14px 16px; margin-bottom:10px; display:block; color:inherit; text-decoration:none; }}
  a.card:hover {{ border-color:var(--navy); }}
  .meta {{ color:var(--soft); font-size:13px; }}
  .tag {{ display:inline-block; background:var(--gold); color:#26241F; border-radius:999px;
         padding:1px 9px; font-size:12px; font-weight:600; margin-left:6px; }}
  dl {{ display:grid; grid-template-columns:max-content 1fr; gap:4px 16px; margin:0; }}
  dt {{ color:var(--soft); }} dd {{ margin:0; overflow-wrap:anywhere; }}
  .msg {{ border-radius:10px; padding:10px 12px; margin:8px 0; max-width:85%;
         white-space:pre-wrap; overflow-wrap:anywhere; }}
  .msg.user {{ background:var(--navy); color:#FAF7F2; margin-left:auto; }}
  .msg.assistant {{ background:var(--bot); }}
  .pager {{ margin-top:16px; }}
  @media (max-width:600px) {{ dl {{ grid-template-columns:1fr; }} dt {{ margin-top:6px; }} .msg {{ max-width:100%; }} }}
</style>
</head>
<body>
<header><a href="/admin">UNLP Studiekompas · gesprekken</a></header>
<main>{body}</main>
</body>
</html>"""
    return HTMLResponse(html)


@router.get("", response_class=HTMLResponse, dependencies=[Depends(require_advisor)])
def overview(leads: bool = False, offset: int = Query(0, ge=0)):
    rows = list_conversations(os.environ["DATABASE_URL"], only_leads=leads, limit=PAGE_SIZE + 1, offset=offset)
    has_more = len(rows) > PAGE_SIZE
    rows = rows[:PAGE_SIZE]

    cards = []
    for r in rows:
        lead = (
            f'<span class="tag">Aanvraag: {escape(r["lead_name"] or r["lead_email"] or "")}</span>'
            if r["lead_email"] else ""
        )
        summary = escape(r["summary"]) if r["summary"] else '<span class="meta">Nog geen samenvatting</span>'
        details = " · ".join(
            part for part in (
                escape(r["recommended_course"]) if r["recommended_course"] else "",
                escape(STEP_LABELS.get(r["recommended_step"], "")) if r["recommended_step"] else "",
            ) if part
        )
        cards.append(f"""
<a class="card" href="/admin/conversations/{r['id']}">
  <div class="meta">{fmt_time(r['started_at'])} · {r['user_messages']} berichten{lead}</div>
  <div>{summary}</div>
  {f'<div class="meta">{details}</div>' if details else ''}
</a>""")

    base = "/admin?leads=true" if leads else "/admin?"
    sep = "&" if leads else ""
    pager = []
    if offset > 0:
        pager.append(f'<a href="{base}{sep}offset={max(offset - PAGE_SIZE, 0)}">← Nieuwer</a>')
    if has_more:
        pager.append(f'<a href="{base}{sep}offset={offset + PAGE_SIZE}">Ouder →</a>')

    body = f"""
<h1>Gesprekken</h1>
<p class="filters">
  <a href="/admin" class="{'' if leads else 'active'}">Alle gesprekken</a>
  <a href="/admin?leads=true" class="{'active' if leads else ''}">Alleen aanvragen</a>
</p>
{''.join(cards) or '<p class="meta">Geen gesprekken gevonden.</p>'}
<p class="pager">{' &nbsp; '.join(pager)}</p>"""
    return page("Studiekompas gesprekken", body)


@router.get("/conversations/{conversation_id}", response_class=HTMLResponse,
            dependencies=[Depends(require_advisor)])
def conversation(conversation_id: int):
    c = get_conversation_detail(os.environ["DATABASE_URL"], conversation_id)
    if not c:
        raise HTTPException(status_code=404)

    def row(label, value):
        return f"<dt>{label}</dt><dd>{escape(str(value)) if value else '-'}</dd>"

    lead_html = ""
    if c["lead_email"]:
        contact = (
            f"Terugbellen op {c['lead_phone']}" if c["lead_contact_preference"] == "telefoon" else "E-mail"
        )
        lead_html = f"""
<h2>Aanvraag</h2>
<div class="card"><dl>
  {row("Naam", c["lead_name"])}
  {row("E-mail", c["lead_email"])}
  {row("Telefoon", c["lead_phone"])}
  {row("Voorkeur", contact)}
  {row("Interesse", c["lead_course_interest"])}
  {row("Motivatie", c["lead_motivation"])}
  {row("Twijfels", c["lead_objections"])}
  {row("Aangevraagd", fmt_time(c["lead_created_at"]))}
</dl></div>"""

    messages = "".join(
        f'<div class="msg {"user" if t.get("role") == "user" else "assistant"}">{escape(t.get("content", ""))}</div>'
        for t in c["transcript"]
    )

    body = f"""
<p><a href="/admin">← Alle gesprekken</a></p>
<h1>Gesprek van {fmt_time(c['started_at'])}</h1>
<div class="card"><dl>
  {row("Samenvatting", c["summary"])}
  {row("Passende opleiding", c["recommended_course"])}
  {row("Vervolgstap", STEP_LABELS.get(c["recommended_step"]))}
  {row("Type bezoeker", c["persona_guess"])}
</dl></div>
{lead_html}
<h2>Gesprek</h2>
{messages or '<p class="meta">Nog geen berichten.</p>'}"""
    return page("Studiekompas gesprek", body)

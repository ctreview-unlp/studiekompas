"""
Advisor overview: a password-protected list of conversations and leads.

Plain server-rendered HTML, so advisors only need a browser and the shared
password. Disabled entirely unless ADMIN_PASSWORD is set. Every value from
the database is HTML-escaped, since transcripts contain whatever visitors
typed.

Login is a form that sets a signed session cookie, so advisors can log out
and sessions expire on their own. The signing key is derived from the
password, so changing ADMIN_PASSWORD logs everyone out.

    ADMIN_USERNAME       (default "unlp")
    ADMIN_PASSWORD       required to enable /admin
    ADMIN_SESSION_HOURS  (default 8) how long a login stays valid
"""

import hashlib
import hmac
import os
import secrets
import time
from html import escape
from urllib.parse import parse_qs, quote
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.notify import STEP_LABELS
from app.rate_limit import RateLimiter, client_ip
from app.retention import conversation_months, lead_months
from app.storage import get_conversation_detail, list_conversations

router = APIRouter(prefix="/admin")

PAGE_SIZE = 50
LOCAL_TZ = ZoneInfo("Europe/Amsterdam")
SESSION_COOKIE = "studiekompas_admin"
# Slows down password guessing: 10 login attempts per IP per 15 minutes.
login_limiter = RateLimiter(max_requests=10, window_seconds=900)


def admin_password() -> str:
    password = os.environ.get("ADMIN_PASSWORD")
    if not password:
        raise HTTPException(status_code=404)
    return password


def session_hours() -> float:
    return float(os.environ.get("ADMIN_SESSION_HOURS", "8"))


def sign(expires_at: int, password: str) -> str:
    key = hashlib.sha256(b"studiekompas-admin-session:" + password.encode()).digest()
    return hmac.new(key, str(expires_at).encode(), hashlib.sha256).hexdigest()


def make_session(password: str) -> str:
    expires_at = int(time.time() + session_hours() * 3600)
    return f"{expires_at}.{sign(expires_at, password)}"


def valid_session(token: str | None, password: str) -> bool:
    try:
        expires_part, signature = (token or "").split(".", 1)
        expires_at = int(expires_part)
    except ValueError:
        return False
    return expires_at > time.time() and hmac.compare_digest(signature, sign(expires_at, password))


def safe_next(target: str | None) -> str:
    """Only redirect back into /admin after login, never to another site."""
    if target and target.startswith("/admin") and not target.startswith("/admin/login"):
        return target
    return "/admin"


def require_advisor(request: Request) -> None:
    password = admin_password()
    if not valid_session(request.cookies.get(SESSION_COOKIE), password):
        target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        raise HTTPException(status_code=303, headers={"Location": f"/admin/login?next={quote(target)}"})


def is_local(request: Request) -> bool:
    return request.url.hostname in ("localhost", "127.0.0.1")


def fmt_time(value) -> str:
    return value.astimezone(LOCAL_TZ).strftime("%d-%m-%Y %H:%M") if value else "-"


def page(title: str, body: str, logged_in: bool = True) -> HTMLResponse:
    logout_button = (
        '<form method="post" action="/admin/logout"><button type="submit">Log uit</button></form>'
        if logged_in else ""
    )
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
  header {{ background:var(--navy); color:#FAF7F2; padding:14px 16px; display:flex;
           align-items:center; justify-content:space-between; gap:12px; }}
  header form {{ margin:0; }}
  header button {{ background:transparent; color:#FAF7F2; border:1px solid rgba(250,247,242,.5);
                  border-radius:8px; padding:5px 12px; font:inherit; cursor:pointer; }}
  header button:hover {{ background:rgba(250,247,242,.12); }}
  .login {{ max-width:360px; margin:40px auto; }}
  .login label {{ display:block; margin:12px 0 4px; }}
  .login input {{ width:100%; padding:9px 10px; border:1px solid var(--border); border-radius:8px;
                 font:inherit; background:#fff; color:var(--ink); }}
  .login button {{ margin-top:16px; width:100%; padding:10px; border:none; border-radius:8px;
                  background:var(--navy); color:#FAF7F2; font:inherit; font-weight:600; cursor:pointer; }}
  .error {{ color:#A33A2B; }}
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
<header><a href="/admin">UNLP Studiekompas · gesprekken</a>{logout_button}</header>
<main>{body}</main>
</body>
</html>"""
    # No caching, so the back button can't show conversations after logging out.
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


def login_page(next_url: str, error: str = "", status_code: int = 200) -> HTMLResponse:
    body = f"""
<form class="login card" method="post" action="/admin/login">
  <h1>Inloggen</h1>
  {f'<p class="error">{escape(error)}</p>' if error else ''}
  <input type="hidden" name="next" value="{escape(next_url)}">
  <label for="username">Gebruikersnaam</label>
  <input id="username" name="username" autocomplete="username" required autofocus>
  <label for="password">Wachtwoord</label>
  <input id="password" name="password" type="password" autocomplete="current-password" required>
  <button type="submit">Inloggen</button>
</form>"""
    response = page("Inloggen · Studiekompas", body, logged_in=False)
    response.status_code = status_code
    return response


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next: str = "/admin"):
    password = admin_password()
    if valid_session(request.cookies.get(SESSION_COOKIE), password):
        return RedirectResponse(safe_next(next), status_code=303)
    return login_page(safe_next(next))


@router.post("/login")
async def login(request: Request):
    password = admin_password()
    # Parsed by hand to avoid adding python-multipart just for one form.
    form = {k: v[0] for k, v in parse_qs((await request.body()).decode()).items()}
    next_url = safe_next(form.get("next"))

    if not login_limiter.allow(client_ip(request)):
        return login_page(next_url, "Te veel pogingen. Probeer het over een kwartier opnieuw.", 429)

    username = os.environ.get("ADMIN_USERNAME", "unlp")
    valid = secrets.compare_digest(form.get("username", "").encode(), username.encode()) & \
        secrets.compare_digest(form.get("password", "").encode(), password.encode())
    if not valid:
        return login_page(next_url, "Gebruikersnaam of wachtwoord klopt niet.", 401)

    response = RedirectResponse(next_url, status_code=303)
    response.set_cookie(
        SESSION_COOKIE, make_session(password), max_age=int(session_hours() * 3600),
        path="/admin", httponly=True, samesite="strict", secure=not is_local(request),
    )
    return response


@router.post("/logout")
def logout():
    response = RedirectResponse("/admin/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/admin")
    return response


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
<p class="meta">Gesprekken worden na {conversation_months()} maanden automatisch verwijderd,
aanvragen (met het bijbehorende gesprek) na {lead_months()} maanden.</p>
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

"""
Usage statistics for management: how often the Studiekompas is used, what
visitors ask about, and what it recommends.

Totals only, never conversation content or contact details, so it has its
own password: people who should see the numbers don't need access to the
conversations in /admin. Shares the look and login mechanism of /admin.

    STATS_USERNAME   (default "unlp")
    STATS_PASSWORD   required to enable /stats

Topics come from the conversation summaries (TOPICS in app/summarize.py);
conversations from before topics existed are labelled with
`python -m app.scripts.label_topics`.
"""

import os
import secrets
from datetime import timedelta
from html import escape
from urllib.parse import parse_qs, quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import admin
from app.admin import fmt_time, is_local, make_session, page, session_hours, valid_session
from app.notify import STEP_LABELS
from app.rate_limit import client_ip
from app.retention import conversation_months
from app.storage import usage_stats
from app.summarize import TOPICS

router = APIRouter(prefix="/stats")

SESSION_COOKIE = "studiekompas_stats"
HEADING = "statistieken"
# Selectable periods: label and number of days (None = everything still stored).
PERIODS = {"30": ("30 dagen", 30), "90": ("90 dagen", 90), "365": ("12 maanden", 365), "alles": ("Alles", None)}
DEFAULT_PERIOD = "90"

STYLE = """<style>
  .tiles { display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:10px; margin-bottom:8px; }
  .tile { background:var(--card); border:1px solid var(--border); border-radius:10px; padding:12px 14px; }
  .tile b { display:block; font-size:24px; line-height:1.2; }
  .bars { display:grid; grid-template-columns:minmax(120px, max-content) 1fr max-content; gap:6px 10px; align-items:center; }
  .bar { height:14px; border-radius:4px; background:var(--navy); min-width:2px; }
  .bar.light { background:var(--border); }
  .track { position:relative; }
  .track .bar { position:absolute; top:0; left:0; }
  .track .bar.light { position:static; }
  .num { color:var(--soft); font-size:13px; text-align:right; white-space:nowrap; }
  /* Narrow screens: label on its own line, bar and number below it. */
  @media (max-width:600px) {
    .bars { grid-template-columns:1fr max-content; gap:2px 10px; }
    .bars > div:nth-child(3n+1) { grid-column:1 / -1; margin-top:6px; }
  }
</style>"""


def stats_password() -> str:
    password = os.environ.get("STATS_PASSWORD")
    if not password:
        raise HTTPException(status_code=404)
    return password


def safe_next(target: str | None) -> str:
    if target and target.startswith("/stats") and not target.startswith("/stats/login"):
        return target
    return "/stats"


def require_viewer(request: Request) -> None:
    if not valid_session(request.cookies.get(SESSION_COOKIE), stats_password()):
        target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        raise HTTPException(status_code=303, headers={"Location": f"/stats/login?next={quote(target)}"})


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next: str = "/stats"):
    if valid_session(request.cookies.get(SESSION_COOKIE), stats_password()):
        return RedirectResponse(safe_next(next), status_code=303)
    return admin.login_page(safe_next(next), home="/stats", heading=HEADING)


@router.post("/login")
async def login(request: Request):
    password = stats_password()
    form = {k: v[0] for k, v in parse_qs((await request.body()).decode()).items()}
    next_url = safe_next(form.get("next"))

    if not admin.login_limiter.allow(client_ip(request)):
        return admin.login_page(next_url, "Te veel pogingen. Probeer het over een kwartier opnieuw.", 429,
                                home="/stats", heading=HEADING)

    username = os.environ.get("STATS_USERNAME", "unlp")
    valid = secrets.compare_digest(form.get("username", "").encode(), username.encode()) & \
        secrets.compare_digest(form.get("password", "").encode(), password.encode())
    if not valid:
        return admin.login_page(next_url, "Gebruikersnaam of wachtwoord klopt niet.", 401,
                                home="/stats", heading=HEADING)

    response = RedirectResponse(next_url, status_code=303)
    response.set_cookie(
        SESSION_COOKIE, make_session(password), max_age=int(session_hours() * 3600),
        path="/stats", httponly=True, samesite="strict", secure=not is_local(request),
    )
    return response


@router.post("/logout")
def logout():
    response = RedirectResponse("/stats/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/stats")
    return response


def pct(part: int, whole: int) -> str:
    return f"{round(100 * part / whole)}%" if whole else "-"


def bar_rows(items: list[tuple[str, int]], total: int) -> str:
    """Label, bar scaled to the largest value, count and share of total."""
    top = max((n for _, n in items), default=0)
    return "".join(
        f'<div>{escape(label)}</div>'
        f'<div><div class="bar" style="width:{100 * n / top if top else 0:.1f}%"></div></div>'
        f'<div class="num">{n} · {pct(n, total)}</div>'
        for label, n in items
    )


def weekly_rows(weekly: list[dict]) -> str:
    """One row per week, gaps filled, newest first: conversations on top of chats opened."""
    if not weekly:
        return ""
    by_week = {w["week"]: w for w in weekly}
    week, last = weekly[0]["week"], weekly[-1]["week"]
    weeks = []
    while week <= last:
        weeks.append(by_week.get(week, {"week": week, "conversations": 0, "opened": 0}))
        week += timedelta(days=7)
    top = max(w["opened"] for w in weeks) or 1
    return "".join(
        f'<div>week van {w["week"].strftime("%d-%m-%Y")}</div>'
        f'<div class="track"><div class="bar light" style="width:{100 * w["opened"] / top:.1f}%"></div>'
        f'<div class="bar" style="width:{100 * w["conversations"] / top:.1f}%"></div></div>'
        f'<div class="num">{w["conversations"]} {"gesprek" if w["conversations"] == 1 else "gesprekken"}'
        f' · {w["opened"]} geopend</div>'
        for w in reversed(weeks)
    )


@router.get("", response_class=HTMLResponse, dependencies=[Depends(require_viewer)])
def overview(periode: str = DEFAULT_PERIOD):
    if periode not in PERIODS:
        periode = DEFAULT_PERIOD
    label, days = PERIODS[periode]
    s = usage_stats(os.environ["DATABASE_URL"], days)
    t = s["totals"]
    conversations = t["conversations"]

    period_links = " ".join(
        f'<a href="/stats?periode={key}" class="{"active" if key == periode else ""}">{escape(name)}</a>'
        for key, (name, _) in PERIODS.items()
    )
    median = t["median_questions"]
    tiles = [
        ("Gesprekken", conversations, "bezoekers die minstens één vraag stelden"),
        ("Chat geopend", t["opened"], "inclusief bezoekers die niets vroegen"),
        ("Vragen gesteld", t["questions"], f"mediaan {median:g} per gesprek".replace(".", ",") if median else ""),
        ("Contactaanvragen", t["leads"], f"{pct(t['leads'], conversations)} van de gesprekken"),
        ("Laatst gebruikt", fmt_time(t["last_used"]), ""),
    ]
    tiles_html = "".join(
        f'<div class="tile"><span class="meta">{escape(name)}</span><b>{escape(str(value))}</b>'
        f'<span class="meta">{escape(note)}</span></div>'
        for name, value, note in tiles
    )

    topics = [(TOPICS.get(r["topic"], r["topic"]), r["n"]) for r in s["topics"]]
    unlabelled = (
        f'<p class="meta">{t["unlabelled"]} gesprekken hebben nog geen onderwerp.</p>'
        if t["unlabelled"] else ""
    )
    steps = [(STEP_LABELS.get(r["step"], r["step"]), r["n"]) for r in s["steps"]]
    courses = [(r["course"], r["n"]) for r in s["courses"]]

    def section(title: str, intro: str, rows_html: str) -> str:
        return (f'<h2>{title}</h2><p class="meta">{intro}</p>'
                f'<div class="card bars">{rows_html}</div>' if rows_html
                else f'<h2>{title}</h2><p class="meta">Nog geen gegevens in deze periode.</p>')

    body = f"""{STYLE}
<h1>Gebruik van het Studiekompas</h1>
<p class="filters">{period_links}</p>
<p class="meta">Gesprekken worden na {conversation_months()} maanden verwijderd, dus de cijfers gaan
hooguit {conversation_months()} maanden terug. Alleen totalen: geen gesprekken of contactgegevens.</p>
<div class="tiles">{tiles_html}</div>
{section("Per week", "Donker: gesprekken met minstens één vraag. Licht: chat geopend.", weekly_rows(s["weekly"]))}
{section("Onderwerpen", "Waar bezoekers naar vragen. Een gesprek kan meerdere onderwerpen hebben; "
         "het percentage is het deel van de gesprekken.", bar_rows(topics, conversations))}
{unlabelled}
{section("Aanbevolen vervolgstap", "Wat het Studiekompas als logische volgende stap zag.",
         bar_rows(steps, conversations))}
{section("Meest aanbevolen opleidingen", "Top 10 van de opleidingen die het best pasten volgens het gesprek.",
         bar_rows(courses, conversations))}"""
    return page(f"Statistieken ({label}) · Studiekompas", body, home="/stats", heading=HEADING)

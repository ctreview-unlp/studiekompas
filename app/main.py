"""
Studiekompas API.

/api/chat calls the real Claude API using the system prompt built from
courses currently in the database. Conversation transcripts are persisted
to Postgres (app/storage.py) instead of kept in memory.

/api/consent records that a visitor accepted the data-use notice before
any conversation starts. /api/chat refuses sessions that haven't, so the
consent gate can't be skipped by calling the API directly.

Because /api/chat is public and every call costs a Claude request, it is
protected by: CORS limited to the UNLP site, a per-client rate limit, a
maximum message length, a cap on turns per conversation, and a cap on how
much history is sent to the model.

When a visitor wants contact with an advisor, the model collects their
details and calls the `save_lead` tool (app/leads.py). After every reply a
background task refreshes the advisor-facing summary (app/summarize.py)
and, when a lead was just saved, emails the advisors (app/notify.py).
Advisors read everything at /admin (app/admin.py).

/demo mounts the frontend folder as static files so the widget demo page
can be shared via a live URL instead of only running locally.
"""

import logging
import os
from uuid import UUID

import anthropic
import psycopg
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.admin import router as admin_router
from app.course_links import link_course_names
from app.enrollment import enforce_enrollment_intent
from app.leads import SAVE_LEAD_TOOL, InvalidLead, clean_lead
from app.notify import send_lead_email
from app.prompts import build_system_prompt, fetch_courses
from app.rate_limit import RateLimiter, client_ip
from app.storage import (
    get_conversation, get_conversation_id, record_consent, save_lead, save_summary,
    save_transcript,
)
from app.summarize import summarize_conversation

load_dotenv()

logger = logging.getLogger("studiekompas")

DATABASE_URL = os.environ["DATABASE_URL"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
# Used to build links to /admin in advisor emails.
PUBLIC_BASE_URL = os.environ.get(
    "PUBLIC_BASE_URL", "https://studiekompas-production.up.railway.app"
).rstrip("/")

# Whether the advisor may collect contact details (save_lead). Off until the
# team is notified of new leads; while off, it refers visitors to email.
LEAD_CAPTURE_ENABLED = os.environ.get("LEAD_CAPTURE", "off").lower() in ("on", "true", "1")

MODEL = "claude-sonnet-5-5"
# "low" is the recommended starting point for chat on Claude Sonnet 5.5: the
# model skips thinking on most simple messages, which keeps replies quick.
EFFORT = "low"
# Retries a safety-classifier decline on another model (Claude API only).
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# Comma-separated list of sites allowed to call the API from a browser.
# The /demo page is served from this API's own origin, so it needs no entry.
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get("ALLOWED_ORIGINS", "https://unlp.nl,https://www.unlp.nl").split(",")
    if o.strip()
]

MAX_MESSAGE_CHARS = 2000
# Only the most recent messages are sent to Claude; the full transcript is still stored.
MAX_HISTORY_MESSAGES = 30
# A real advice conversation never needs this many turns; past it, hand off to a human.
MAX_USER_TURNS = 40
# Model calls per visitor message: one reply, plus a follow-up after a tool call.
MAX_TOOL_ROUNDS = 3

# Shown when the model declines to answer (stop_reason "refusal").
REFUSAL_REPLY = (
    "Daar kan ik je helaas niet mee helpen. Heb je een vraag over een opleiding, "
    "dan denk ik graag met je mee, of neem contact op met een opleidingsadviseur. "
    "[Mail een adviseur](mailto:info@unlp.nl)"
)

CONTACT_FALLBACK_REPLY = (
    "We hebben al een flink gesprek gevoerd. Om je verder goed te helpen, kun je "
    "het beste contact opnemen met een opleidingsadviseur van UNLP. "
    "[Mail een adviseur](mailto:info@unlp.nl)"
)

chat_limiter = RateLimiter(max_requests=20, window_seconds=300)
consent_limiter = RateLimiter(max_requests=10, window_seconds=300)

# No public API docs: /docs, /redoc and /openapi.json would list every endpoint.
app = FastAPI(title="Studiekompas API", docs_url=None, redoc_url=None, openapi_url=None)


def trim_history(history: list[dict], max_messages: int) -> list[dict]:
    """
    Keep only the last `max_messages` turns for the model, so long
    conversations don't grow the cost of every request without bound.
    The Messages API requires the first message to be from the user,
    so leading assistant turns left over from the cut are dropped.
    """
    trimmed = history[-max_messages:]
    while trimmed and trimmed[0].get("role") != "user":
        trimmed = trimmed[1:]
    return trimmed


# Limited to the UNLP website (see ALLOWED_ORIGINS) — see Ch. 18 (data
# handling) for why this isn't just a technical detail once real visitor
# data is involved. For local development, set ALLOWED_ORIGINS in .env.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.exception_handler(psycopg.Error)
def database_error(request: Request, exc: psycopg.Error):
    logger.exception("Database error on %s", request.url.path)
    return JSONResponse(status_code=503, content={"detail": "database_unavailable"})

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

app.include_router(admin_router)


class ChatRequest(BaseModel):
    session_id: UUID
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


class ChatResponse(BaseModel):
    reply: str


class ConsentRequest(BaseModel):
    session_id: UUID


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {"message": "Studiekompas API is running."}


@app.post("/api/consent")
def consent(req: ConsentRequest, request: Request):
    if not consent_limiter.allow(client_ip(request)):
        raise HTTPException(status_code=429, detail="rate_limited")
    record_consent(DATABASE_URL, str(req.session_id))
    return {"status": "ok"}


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest, request: Request, background: BackgroundTasks):
    if not chat_limiter.allow(client_ip(request)):
        raise HTTPException(status_code=429, detail="rate_limited")

    session_id = str(req.session_id)
    history, consent_given = get_conversation(DATABASE_URL, session_id)
    if not consent_given:
        raise HTTPException(status_code=403, detail="consent_required")

    history.append({"role": "user", "content": req.message})

    user_turns = sum(1 for turn in history if turn.get("role") == "user")
    if user_turns > MAX_USER_TURNS:
        history.append({"role": "assistant", "content": CONTACT_FALLBACK_REPLY})
        save_transcript(DATABASE_URL, session_id, history)
        return ChatResponse(reply=CONTACT_FALLBACK_REPLY)

    courses = fetch_courses(DATABASE_URL)
    system_prompt = build_system_prompt(courses, lead_capture=LEAD_CAPTURE_ENABLED)

    saved_lead = {}

    def run_tool(block) -> dict:
        """Execute a tool call from the model and build its tool_result."""
        if block.name != "save_lead" or not LEAD_CAPTURE_ENABLED:
            return {"type": "tool_result", "tool_use_id": block.id, "is_error": True,
                    "content": f"Onbekende tool: {block.name}"}
        try:
            lead = clean_lead(block.input)
        except InvalidLead as e:
            return {"type": "tool_result", "tool_use_id": block.id, "is_error": True,
                    "content": str(e)}
        save_lead(DATABASE_URL, session_id, lead)
        saved_lead.clear()
        saved_lead.update(lead)
        return {"type": "tool_result", "tool_use_id": block.id,
                "content": "Gegevens opgeslagen en doorgegeven aan een opleidingsadviseur."}

    messages = trim_history(history, MAX_HISTORY_MESSAGES)
    reply_parts = []
    try:
        for _ in range(MAX_TOOL_ROUNDS):
            response = claude.beta.messages.create(
                model=MODEL,
                # Thinking counts towards max_tokens, so leave room beyond the reply.
                max_tokens=4000,
                output_config={"effort": EFFORT},
                betas=[FALLBACK_BETA],
                fallbacks="default",
                **({"tools": [SAVE_LEAD_TOOL]} if LEAD_CAPTURE_ENABLED else {}),
                # The system prompt (instructions + full course list) is identical
                # for every request until the course data changes, so cache it.
                system=[{
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=messages,
            )
            if response.stop_reason == "refusal":
                logger.warning(
                    "Refusal (category=%s) for session %s",
                    getattr(response.stop_details, "category", None), session_id,
                )
                reply_parts = [REFUSAL_REPLY]
                break
            # Read blocks by type: a response can start with a (usually empty) thinking block.
            text = "".join(b.text for b in response.content if b.type == "text").strip()
            if text:
                reply_parts.append(text)
            if response.stop_reason != "tool_use":
                break
            tool_results = [run_tool(b) for b in response.content if b.type == "tool_use"]
            # Thinking blocks go back unchanged with the rest of the turn; the
            # fallback marker is an audit block that may be dropped.
            messages = messages + [
                {"role": "assistant", "content": [
                    b.model_dump(exclude_none=True) for b in response.content if b.type != "fallback"
                ]},
                {"role": "user", "content": tool_results},
            ]
    except anthropic.APIError:
        logger.exception("Claude API call failed for session %s", session_id)
        raise HTTPException(status_code=503, detail="model_unavailable")

    # Only the visible text is kept in the transcript; the tool exchange is
    # internal. If the model spoke both before and after a tool call, the
    # last part is the one that reflects the tool's outcome.
    reply_text = reply_parts[-1] if reply_parts else ""
    if not reply_text:
        logger.warning("Empty reply (stop_reason=%s) for session %s", response.stop_reason, session_id)
        raise HTTPException(status_code=503, detail="empty_reply")

    reply_text, removed = enforce_enrollment_intent(reply_text, history)
    if removed:
        logger.warning("Removed unrequested enrollment link for session %s", session_id)
    reply_text = link_course_names(reply_text, courses)

    history.append({"role": "assistant", "content": reply_text})
    save_transcript(DATABASE_URL, session_id, history)

    background.add_task(
        after_reply, session_id, history, [c["name"] for c in courses], dict(saved_lead) or None
    )
    return ChatResponse(reply=reply_text)


def after_reply(session_id: str, history: list[dict], course_names: list[str], lead: dict | None) -> None:
    """
    Runs after the response has been sent, so the visitor never waits on it.
    Refreshes the advisor summary, then emails the advisors if a lead was
    just saved. Failures are logged and never affect the conversation.
    """
    summary = None
    try:
        summary = summarize_conversation(claude, MODEL, history, course_names)
        save_summary(DATABASE_URL, session_id, summary)
    except Exception:
        logger.exception("Summary failed for session %s", session_id)

    if lead:
        try:
            conversation_id = get_conversation_id(DATABASE_URL, session_id)
            url = f"{PUBLIC_BASE_URL}/admin/conversations/{conversation_id}" if conversation_id else None
            send_lead_email(lead, summary, url)
        except Exception:
            logger.exception("Lead notification failed for session %s", session_id)


# Mounted last so it doesn't shadow the API routes above.
app.mount("/demo", StaticFiles(directory="frontend", html=True), name="demo")
"""
Studiekompas API.

/api/chat calls the real Claude API using the system prompt built from
courses currently in the database. Conversation history is kept in memory
per session for now — swap for Postgres-backed storage (the `conversations`
table already exists) as a next step.

/demo mounts the frontend folder as static files so the widget demo page
can be shared via a live URL instead of only running locally.
"""

import os

import anthropic
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.prompts import build_system_prompt, fetch_courses

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

app = FastAPI(title="Studiekompas API")

# Wide open for now during local development. Tighten this to the real UNLP
# website origin(s) before going live — see Ch. 18 (data handling) for why
# this isn't just a technical detail once real visitor data is involved.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# In-memory conversation history, keyed by session_id.
# Fine for demo/testing; replace with the `conversations` table before
# this is used with real visitors (state is lost on every redeploy).
_conversations: dict[str, list[dict]] = {}


class ChatRequest(BaseModel):
    session_id: str
    message: str


class ChatResponse(BaseModel):
    reply: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {"message": "Studiekompas API is running."}


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    history = _conversations.setdefault(req.session_id, [])
    history.append({"role": "user", "content": req.message})

    courses = fetch_courses(DATABASE_URL)
    system_prompt = build_system_prompt(courses)

    response = claude.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        system=system_prompt,
        messages=history,
    )

    reply_text = "".join(
        block.text for block in response.content if block.type == "text"
    )

    history.append({"role": "assistant", "content": reply_text})

    return ChatResponse(reply=reply_text)


# Mounted last so it doesn't shadow the API routes above.
app.mount("/demo", StaticFiles(directory="frontend", html=True), name="demo")
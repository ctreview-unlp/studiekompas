"""
Studiekompas API.

/api/chat calls the real Claude API using the system prompt built from
courses currently in the database. Conversation transcripts are persisted
to Postgres (app/storage.py) instead of kept in memory.

/api/consent records that a visitor accepted the data-use notice before
any conversation starts.

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
from app.storage import get_transcript, save_transcript, record_consent

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

app = FastAPI(title="Studiekompas API")


def append_missing_info_button(reply_text: str, courses: list[dict]) -> str:
    """
    Safety net: if the reply discusses a specific course by name but doesn't
    already include a CTA button, add one linking to that course's info page.

    Relying purely on the system prompt instruction to include this button
    isn't 100% reliable — LLMs don't follow even strongly-worded "always do
    X" instructions with perfect consistency, especially in a large system
    prompt with many competing rules. This deterministic check catches
    whatever slips through, so the button reliably appears rather than
    depending entirely on the model remembering.
    """
    if "](" in reply_text:
        return reply_text  # already has a CTA button (e.g. enrollment), don't add a second

    for course in courses:
        if course.get("url") and course["name"].lower() in reply_text.lower():
            return reply_text + f"\n\n[Bekijk de opleiding]({course['url']})"

    return reply_text

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


class ChatRequest(BaseModel):
    session_id: str
    message: str


class ChatResponse(BaseModel):
    reply: str


class ConsentRequest(BaseModel):
    session_id: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {"message": "Studiekompas API is running."}


@app.post("/api/consent")
def consent(req: ConsentRequest):
    record_consent(DATABASE_URL, req.session_id)
    return {"status": "ok"}


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    history = get_transcript(DATABASE_URL, req.session_id)
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
    reply_text = append_missing_info_button(reply_text, courses)

    history.append({"role": "assistant", "content": reply_text})
    save_transcript(DATABASE_URL, req.session_id, history)

    return ChatResponse(reply=reply_text)


# Mounted last so it doesn't shadow the API routes above.
app.mount("/demo", StaticFiles(directory="frontend", html=True), name="demo")
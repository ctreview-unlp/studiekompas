import uuid
from types import SimpleNamespace

import anthropic
import httpx
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.rate_limit import RateLimiter

COURSES = [{
    "name": "NLP Practitioner", "category": "NLP", "level": "Beginner", "prerequisites": None,
    "description": "Basisopleiding.", "price": None, "upcoming_schedule": None,
    "certification": None, "url": "https://unlp.nl/practitioner",
}]


class FakeDB:
    def __init__(self, transcript=None, consent=True):
        self.transcript = transcript or []
        self.consent = consent
        self.saved = None

    def get_conversation(self, _db, _session_id):
        return list(self.transcript), self.consent

    def save_transcript(self, _db, _session_id, transcript):
        self.saved = transcript


def text_response(text):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason="end_turn")


@pytest.fixture
def setup(monkeypatch):
    """Wires fake storage and a fake Claude client into the app."""
    db = FakeDB()
    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        return text_response("Wat brengt je hier vandaag?")

    monkeypatch.setattr(main, "get_conversation", db.get_conversation)
    monkeypatch.setattr(main, "save_transcript", db.save_transcript)
    monkeypatch.setattr(main, "fetch_courses", lambda _db: COURSES)
    monkeypatch.setattr(main.claude.messages, "create", fake_create)
    monkeypatch.setattr(main, "chat_limiter", RateLimiter(max_requests=100, window_seconds=60))
    return SimpleNamespace(db=db, calls=calls, client=TestClient(main.app))


def post_chat(client, message="Hallo", session_id=None):
    return client.post("/api/chat", json={"session_id": session_id or str(uuid.uuid4()), "message": message})


def test_successful_chat_saves_transcript_and_caches_system_prompt(setup):
    res = post_chat(setup.client)

    assert res.status_code == 200
    assert res.json()["reply"] == "Wat brengt je hier vandaag?"
    assert [t["role"] for t in setup.db.saved] == ["user", "assistant"]
    assert setup.calls[0]["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_chat_refused_without_consent(setup):
    setup.db.consent = False
    res = post_chat(setup.client)

    assert res.status_code == 403
    assert setup.calls == []
    assert setup.db.saved is None


def test_invalid_session_id_rejected(setup):
    res = post_chat(setup.client, session_id="not-a-uuid")
    assert res.status_code == 422


def test_overlong_message_rejected(setup):
    res = post_chat(setup.client, message="x" * (main.MAX_MESSAGE_CHARS + 1))
    assert res.status_code == 422
    assert setup.calls == []


def test_rate_limit_returns_429(setup, monkeypatch):
    monkeypatch.setattr(main, "chat_limiter", RateLimiter(max_requests=1, window_seconds=60))
    assert post_chat(setup.client).status_code == 200
    assert post_chat(setup.client).status_code == 429


def test_claude_failure_returns_503_and_saves_nothing(setup, monkeypatch):
    def failing_create(**_kwargs):
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        raise anthropic.APIConnectionError(request=request)

    monkeypatch.setattr(main.claude.messages, "create", failing_create)
    res = post_chat(setup.client)

    assert res.status_code == 503
    assert setup.db.saved is None


def test_turn_cap_hands_off_without_calling_claude(setup):
    setup.db.transcript = [
        {"role": role, "content": "..."}
        for _ in range(main.MAX_USER_TURNS)
        for role in ("user", "assistant")
    ]
    res = post_chat(setup.client)

    assert res.status_code == 200
    assert "mailto:info@unlp.nl" in res.json()["reply"]
    assert setup.calls == []


def test_long_history_is_trimmed_before_sending(setup):
    setup.db.transcript = [
        {"role": role, "content": "..."}
        for _ in range(25)
        for role in ("user", "assistant")
    ]
    post_chat(setup.client)

    sent = setup.calls[0]["messages"]
    assert len(sent) <= main.MAX_HISTORY_MESSAGES
    assert sent[0]["role"] == "user"
    assert sent[-1]["content"] == "Hallo"

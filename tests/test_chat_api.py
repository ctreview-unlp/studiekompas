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


class Block(SimpleNamespace):
    def model_dump(self, exclude_none=False):
        return dict(vars(self))


def text_response(text):
    return SimpleNamespace(content=[Block(type="text", text=text)], stop_reason="end_turn")


def tool_response(tool_input):
    return SimpleNamespace(
        content=[Block(type="tool_use", id="toolu_1", name="save_lead", input=tool_input)],
        stop_reason="tool_use",
    )


@pytest.fixture
def setup(monkeypatch):
    """Wires fake storage and a fake Claude client into the app."""
    db = FakeDB()
    calls = []
    replies = []  # queued fake model responses; defaults to a plain text reply
    leads, summaries, emails = [], [], []

    def fake_create(**kwargs):
        calls.append(kwargs)
        return replies.pop(0) if replies else text_response("Wat brengt je hier vandaag?")

    monkeypatch.setattr(main, "get_conversation", db.get_conversation)
    monkeypatch.setattr(main, "save_transcript", db.save_transcript)
    monkeypatch.setattr(main, "fetch_courses", lambda _db: COURSES)
    monkeypatch.setattr(main.claude.messages, "create", fake_create)
    monkeypatch.setattr(main, "chat_limiter", RateLimiter(max_requests=100, window_seconds=60))
    monkeypatch.setattr(main, "save_lead", lambda _db, _sid, lead: leads.append(lead) or 1)
    monkeypatch.setattr(main, "summarize_conversation",
                        lambda *_a: {"summary": "Starter zoekt een opleiding."})
    monkeypatch.setattr(main, "save_summary", lambda _db, _sid, summary: summaries.append(summary))
    monkeypatch.setattr(main, "get_conversation_id", lambda _db, _sid: 42)
    monkeypatch.setattr(main, "send_lead_email", lambda *a: emails.append(a))
    return SimpleNamespace(db=db, calls=calls, replies=replies, leads=leads, summaries=summaries,
                           emails=emails, client=TestClient(main.app))


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


def test_summary_refreshed_after_each_reply(setup):
    post_chat(setup.client)
    assert setup.summaries == [{"summary": "Starter zoekt een opleiding."}]
    assert setup.emails == []


def test_lead_saved_and_advisors_emailed(setup):
    setup.replies[:] = [
        tool_response({"name": "Sanne", "email": "Sanne@Example.nl", "contact_preference": "email",
                       "course_interest": "NLP Practitioner"}),
        text_response("Dank je Sanne, ik heb je gegevens doorgegeven aan een adviseur."),
    ]
    res = post_chat(setup.client, message="Ja, mijn naam is Sanne, sanne@example.nl")

    assert res.status_code == 200
    assert res.json()["reply"].startswith("Dank je Sanne")
    assert setup.leads[0]["email"] == "sanne@example.nl"
    # The model got the tool result back before writing its final reply.
    tool_result = setup.calls[1]["messages"][-1]["content"][0]
    assert tool_result["type"] == "tool_result" and not tool_result.get("is_error")
    lead, summary, url = setup.emails[0]
    assert lead["name"] == "Sanne"
    assert url.endswith("/admin/conversations/42")
    # Only the visible reply is stored, not the tool exchange.
    assert all(isinstance(t["content"], str) for t in setup.db.saved)


def test_invalid_lead_is_not_saved_and_model_is_told(setup):
    setup.replies[:] = [
        tool_response({"name": "Sanne", "email": "sanne-at-example", "contact_preference": "email"}),
        text_response("Klopt je e-mailadres? Het lijkt niet helemaal goed te gaan."),
    ]
    post_chat(setup.client)

    assert setup.leads == []
    assert setup.emails == []
    assert setup.calls[1]["messages"][-1]["content"][0]["is_error"] is True

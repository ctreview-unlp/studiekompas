import json

import httpx
import pytest

import app.trengo as trengo

LEAD = {"name": "Sanne <b>", "email": "sanne@example.nl", "contact_preference": "telefoon", "phone": "0612345678"}
SUMMARY = {"summary": "Starter zonder NLP-ervaring, twijfelt over de prijs."}
URL = "https://example.com/admin/conversations/7"
REAL_CLIENT = httpx.Client


@pytest.fixture
def fake_trengo(monkeypatch):
    """Records the requests send_lead makes and answers like the Trengo API."""
    monkeypatch.setenv("TRENGO_API_TOKEN", "test-token")
    monkeypatch.setenv("TRENGO_CHANNEL_ID", "123")
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append((request.url.path, body, request.headers["authorization"]))
        if request.url.path.endswith("/contacts"):
            return httpx.Response(201, json={"id": 555})
        if request.url.path.endswith("/tickets"):
            return httpx.Response(201, json={"id": 999})
        return httpx.Response(200, json={"id": 1})

    monkeypatch.setattr(trengo.httpx, "Client",
                        lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(handler), **kw))
    return requests


def test_new_lead_opens_ticket_with_summary_and_transcript_link(fake_trengo):
    ticket_id = trengo.send_lead(LEAD, SUMMARY, URL)

    assert ticket_id == 999
    (contact_path, contact, auth), (ticket_path, ticket, _), (note_path, note, _) = fake_trengo
    assert auth == "Bearer test-token"
    assert contact_path == "/api/v2/channels/123/contacts" and contact["identifier"] == "sanne@example.nl"
    assert ticket["contact_id"] == "555" and ticket["channel_id"] == 123
    assert "wil teruggebeld worden" in ticket["subject"]
    assert note_path == "/api/v2/tickets/999/messages" and note["internal_note"] is True
    assert SUMMARY["summary"] in note["message"]
    assert URL in note["message"]
    assert "terugbellen op 0612345678" in note["message"]
    assert "<b>" not in note["message"].split("Naam: ")[1].split("<br>")[0]  # visitor input is escaped


def test_update_adds_note_to_existing_ticket(fake_trengo):
    assert trengo.send_lead(LEAD, SUMMARY, URL, existing_ticket_id=42) == 42
    assert [path for path, _, _ in fake_trengo] == ["/api/v2/tickets/42/messages"]
    assert "Bijgewerkte gegevens" in fake_trengo[0][1]["message"]


def test_api_error_is_raised(fake_trengo, monkeypatch):
    monkeypatch.setattr(trengo.httpx, "Client", lambda **kw: REAL_CLIENT(
        transport=httpx.MockTransport(lambda r: httpx.Response(401, json={"message": "Unauthenticated"})), **kw))
    with pytest.raises(trengo.TrengoError, match="401"):
        trengo.send_lead(LEAD, SUMMARY, URL)


def test_not_configured_without_token_or_channel(monkeypatch):
    monkeypatch.delenv("TRENGO_API_TOKEN", raising=False)
    monkeypatch.setenv("TRENGO_CHANNEL_ID", "123")
    assert not trengo.configured()

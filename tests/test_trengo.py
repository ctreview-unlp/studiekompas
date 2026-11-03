import json

import httpx
import pytest

import app.trengo as trengo

LEAD = {"name": "Sanne", "email": "sanne@example.nl", "contact_preference": "telefoon", "phone": "0612345678"}
SUMMARY = {"summary": "Starter zonder NLP-ervaring, twijfelt over de prijs."}
URL = "https://example.com/admin/conversations/7"
REAL_CLIENT = httpx.Client


@pytest.fixture
def fake_trengo(monkeypatch):
    """Records the requests send_lead makes and answers like the Trengo API."""
    monkeypatch.setenv("TRENGO_API_TOKEN", "test-token")
    monkeypatch.setenv("TRENGO_CHANNEL_ID", "123")
    monkeypatch.setenv("TRENGO_TEAM_ID", "77")
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append((request.url.path, body, request.headers["authorization"]))
        if request.url.path.endswith("/contacts"):
            return httpx.Response(201, json={"id": 555})
        if request.url.path.endswith("/tickets"):
            return httpx.Response(201, json={"id": 999})
        if request.url.path.endswith("/assign"):
            return httpx.Response(200)  # empty body, like the real API
        return httpx.Response(200, json={"id": 1})

    monkeypatch.setattr(trengo.httpx, "Client",
                        lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(handler), **kw))
    return requests


def test_new_lead_opens_ticket_with_summary_and_transcript_link(fake_trengo):
    ticket_id = trengo.send_lead(LEAD, SUMMARY, URL)

    assert ticket_id == 999
    (contact_path, contact, auth), (ticket_path, ticket, _), (note_path, note, _), (assign_path, assign, _) = fake_trengo
    assert auth == "Bearer test-token"
    assert contact_path == "/api/v2/channels/123/contacts" and contact["identifier"] == "sanne@example.nl"
    assert ticket["contact_id"] == "555" and ticket["channel_id"] == 123
    assert "wil teruggebeld worden" in ticket["subject"]
    assert ticket["subject"].startswith("Studiekompas:")  # Trengo colours tickets by this
    assert note_path == "/api/v2/tickets/999/messages" and note["internal_note"] is True
    assert SUMMARY["summary"] in note["message"]
    assert URL in note["message"]
    assert "terugbellen op 0612345678" in note["message"]
    assert "Naam: Sanne\nE-mail: sanne@example.nl\n" in note["message"]  # plain text, one item per line
    # The note assigns the ticket to the token's user; hand it to the team after.
    assert assign_path == "/api/v2/tickets/999/assign" and assign == {"type": "team", "team_id": 77}


def test_without_team_ticket_is_not_reassigned(fake_trengo, monkeypatch):
    monkeypatch.delenv("TRENGO_TEAM_ID")
    trengo.send_lead(LEAD, SUMMARY, URL)
    assert [path for path, _, _ in fake_trengo][-1] == "/api/v2/tickets/999/messages"


def test_note_shows_optional_phone_for_email_contact():
    note = trengo.note_text({**LEAD, "contact_preference": "email"}, None, None)
    assert "Contact: via e-mail\nTelefoon: 0612345678" in note


def test_update_adds_note_to_existing_ticket(fake_trengo):
    assert trengo.send_lead(LEAD, SUMMARY, URL, existing_ticket_id=42) == 42
    # Only the note: the ticket keeps whoever the team assigned it to.
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

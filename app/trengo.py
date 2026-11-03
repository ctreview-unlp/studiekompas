"""
Contact requests into Trengo, where Student Support handles most incoming
messages.

When a visitor leaves their details, a ticket is opened for them on the
info@unlp.nl email channel with the AI summary of the conversation and a
link to the full transcript in /admin, as an internal note (Trengo confirmed
internal notes aren't sent to the customer). Replies from the team go to
the visitor's own email address. If the visitor updates their details later
in the same conversation, a note is added to the same ticket.

API reference: https://developers.trengo.com (Bearer token, 120 req/min).

    TRENGO_API_TOKEN   API token of a dedicated Trengo user for Studiekompas, not
                       a staff member's personal token (Settings > Integrations > REST API)
    TRENGO_CHANNEL_ID  id of the info@unlp.nl email channel
"""

import os
from html import escape

import httpx

API = "https://app.trengo.com/api/v2"


class TrengoError(Exception):
    pass


def configured() -> bool:
    return bool(os.environ.get("TRENGO_API_TOKEN") and os.environ.get("TRENGO_CHANNEL_ID"))


def subject_for(lead: dict) -> str:
    want = "wil teruggebeld worden" if lead.get("contact_preference") == "telefoon" else "wil contact"
    return f"Studiekompas: {lead.get('name') or lead['email']} {want}"


def note_html(lead: dict, summary: dict | None, transcript_url: str | None, update: bool = False) -> str:
    """Contact details, the AI summary and a link to the full conversation."""
    contact = (
        f"terugbellen op {escape(lead['phone'])}" if lead.get("contact_preference") == "telefoon"
        else "via e-mail"
    )
    lines = [
        "<b>Bijgewerkte gegevens van deze bezoeker</b>" if update
        else "<b>Contactverzoek via het Studiekompas</b> (AI-studieadviseur op unlp.nl)",
        f"Naam: {escape(lead.get('name') or '-')}",
        f"E-mail: {escape(lead['email'])}",
        f"Contact: {contact}",
    ]
    if summary and summary.get("summary"):
        lines += ["", "<b>AI-samenvatting</b>", escape(summary["summary"])]
    if transcript_url:
        lines += ["", f'<a href="{escape(transcript_url)}">Volledig gesprek bekijken</a>']
    return "<br>".join(lines)


def send_lead(lead: dict, summary: dict | None, transcript_url: str | None,
              existing_ticket_id: int | None = None) -> int:
    """Open a ticket for the lead (or add to its existing one); returns the ticket id."""
    channel_id = int(os.environ["TRENGO_CHANNEL_ID"])
    headers = {
        "Authorization": f"Bearer {os.environ['TRENGO_API_TOKEN']}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    with httpx.Client(base_url=API, headers=headers, timeout=20) as http:
        def call(path: str, body: dict) -> dict:
            resp = http.post(path, json=body)
            if resp.status_code >= 400:
                raise TrengoError(f"POST {path} -> {resp.status_code}: {resp.text[:300]}")
            return resp.json()

        ticket_id = existing_ticket_id
        if ticket_id is None:
            # Returns the existing contact if this email address is already known.
            contact = call(f"/channels/{channel_id}/contacts", {
                "channel_id": channel_id,
                "identifier": lead["email"],
                "name": lead.get("name") or lead["email"],
            })
            ticket = call("/tickets", {
                "channel_id": channel_id,
                "contact_id": str(contact["id"]),
                "subject": subject_for(lead),
            })
            ticket_id = int(ticket["id"])
        call(f"/tickets/{ticket_id}/messages", {
            "message": note_html(lead, summary, transcript_url, update=existing_ticket_id is not None),
            "internal_note": True,
        })
    return ticket_id

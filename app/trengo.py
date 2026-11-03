"""
Contact requests into Trengo, where Student Support handles most incoming
messages.

When a visitor leaves their details, a ticket is opened for them on the
info@unlp.nl email channel with the AI summary of the conversation and a
link to the full transcript in /admin, as an internal note (Trengo confirmed
internal notes aren't sent to the customer). Replies from the team go to
the visitor's own email address. If the visitor updates their details later
in the same conversation, a note is added to the same ticket.

Trengo assigns a ticket to whoever adds the first note, which is the token's
user, so new tickets are handed to the team afterwards; that clears the user
and later notes leave the assignment alone. Notes are plain text: Trengo
strips HTML from them, so line breaks are newlines and the link a bare URL.

API reference: https://developers.trengo.com (Bearer token, 120 req/min).

    TRENGO_API_TOKEN   API token of a dedicated Trengo user for Studiekompas, not
                       a staff member's personal token (Settings > Integrations > REST API)
    TRENGO_CHANNEL_ID  id of the info@unlp.nl email channel
    TRENGO_TEAM_ID     team new tickets go to (UNLP Student Support); without
                       it they stay assigned to the token's user
"""

import os

import httpx

API = "https://app.trengo.com/api/v2"


class TrengoError(Exception):
    pass


def configured() -> bool:
    return bool(os.environ.get("TRENGO_API_TOKEN") and os.environ.get("TRENGO_CHANNEL_ID"))


def subject_for(lead: dict) -> str:
    # Keep "Studiekompas" in the subject: a Trengo rule colours these tickets by it.
    want = "wil teruggebeld worden" if lead.get("contact_preference") == "telefoon" else "wil contact"
    return f"Studiekompas: {lead.get('name') or lead['email']} {want}"


def note_text(lead: dict, summary: dict | None, transcript_url: str | None, update: bool = False) -> str:
    """Contact details, the AI summary and a link to the full conversation."""
    contact = (
        f"terugbellen op {lead['phone']}" if lead.get("contact_preference") == "telefoon"
        else "via e-mail"
    )
    lines = [
        "Bijgewerkte gegevens van deze bezoeker" if update
        else "Contactverzoek via het Studiekompas (AI-studieadviseur op unlp.nl)",
        "",
        f"Naam: {lead.get('name') or '-'}",
        f"E-mail: {lead['email']}",
        f"Contact: {contact}",
    ]
    if lead.get("phone") and lead.get("contact_preference") != "telefoon":
        lines.append(f"Telefoon: {lead['phone']}")
    if summary and summary.get("summary"):
        lines += ["", "AI-samenvatting:", summary["summary"]]
    if transcript_url:
        lines += ["", f"Volledig gesprek: {transcript_url}"]
    return "\n".join(lines)


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
            return resp.json() if resp.content else {}  # /assign answers with an empty body

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
            "message": note_text(lead, summary, transcript_url, update=existing_ticket_id is not None),
            "internal_note": True,
        })
        team_id = os.environ.get("TRENGO_TEAM_ID")
        if existing_ticket_id is None and team_id:
            call(f"/tickets/{ticket_id}/assign", {"type": "team", "team_id": int(team_id)})
    return ticket_id

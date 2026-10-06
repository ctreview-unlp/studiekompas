"""
Email notification to UNLP advisors when a visitor leaves their details.

Sent over SMTP, so it works with whatever mail provider UNLP already uses
(Google Workspace, Microsoft 365, or a transactional service with SMTP
access). Configured entirely through environment variables; if they are
not set, notifications are skipped and leads are still visible in /admin.

    SMTP_HOST, SMTP_PORT (default 587), SMTP_USERNAME, SMTP_PASSWORD
    SMTP_FROM          sender address (defaults to SMTP_USERNAME)
    LEAD_NOTIFY_TO     comma-separated advisor addresses
"""

import logging
import os
import smtplib
from email.message import EmailMessage

logger = logging.getLogger("studiekompas")

STEP_LABELS = {
    "enroll": "Inschrijven",
    "info_evening": "Informatieavond",
    "advice_call": "Adviesgesprek",
    "brochure": "Brochure",
    "human_handoff": "Doorverwijzen naar een adviseur",
    "none": "Nog geen duidelijke vervolgstap",
}


def build_lead_email(lead: dict, summary: dict | None, conversation_url: str | None) -> EmailMessage:
    contact_line = (
        f"Wil teruggebeld worden op {lead.get('phone')}"
        if lead.get("contact_preference") == "telefoon"
        else "Wil contact via e-mail"
    )
    lines = [
        "Een bezoeker heeft via de Studiekompas gevraagd om contact met een opleidingsadviseur.",
        "",
        f"Naam:       {lead.get('name', '')}",
        f"E-mail:     {lead.get('email', '')}",
        f"Telefoon:   {lead.get('phone') or '-'}",
        f"Voorkeur:   {contact_line}",
        "",
        f"Interesse:  {lead.get('course_interest') or '-'}",
        f"Motivatie:  {lead.get('motivation') or '-'}",
        f"Twijfels:   {lead.get('objections') or '-'}",
    ]
    if summary:
        lines += [
            "",
            "Samenvatting van het gesprek:",
            summary.get("summary", ""),
            "",
            f"Passende opleiding: {summary.get('recommended_course') or '-'}",
            f"Vervolgstap:        {STEP_LABELS.get(summary.get('recommended_step'), '-')}",
        ]
    if conversation_url:
        lines += ["", f"Volledig gesprek: {conversation_url}"]

    msg = EmailMessage()
    msg["Subject"] = f"Nieuwe aanvraag via Studiekompas: {lead.get('name', '')}"
    msg["Reply-To"] = lead.get("email", "")
    msg.set_content("\n".join(lines))
    return msg


def send_lead_email(lead: dict, summary: dict | None, conversation_url: str | None) -> bool:
    """Send the notification. Returns False (and logs) if unconfigured or failed."""
    host = os.environ.get("SMTP_HOST")
    recipients = [a.strip() for a in os.environ.get("LEAD_NOTIFY_TO", "").split(",") if a.strip()]
    if not host or not recipients:
        logger.warning("Lead email skipped: SMTP_HOST or LEAD_NOTIFY_TO not configured")
        return False

    username = os.environ.get("SMTP_USERNAME")
    msg = build_lead_email(lead, summary, conversation_url)
    msg["From"] = os.environ.get("SMTP_FROM") or username
    msg["To"] = ", ".join(recipients)

    try:
        with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587")), timeout=20) as smtp:
            smtp.starttls()
            if username:
                smtp.login(username, os.environ.get("SMTP_PASSWORD", ""))
            smtp.send_message(msg)
        return True
    except (smtplib.SMTPException, OSError):
        logger.exception("Lead email failed")
        return False

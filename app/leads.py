"""
Lead capture: the `save_lead` tool the advisor model can call once a
visitor has given their contact details and agreed to be contacted.

The model decides *when* to call it (the system prompt sets the rules);
this module decides whether what it passed is usable. Anything invalid is
sent back to the model as an error, so it can ask the visitor again
instead of confirming something that wasn't saved.
"""

import re

SAVE_LEAD_TOOL = {
    "name": "save_lead",
    "description": (
        "Geef de contactgegevens van de bezoeker door aan een UNLP-opleidingsadviseur, "
        "die daarna contact opneemt. Gebruik dit alleen als de bezoeker zelf zijn naam en "
        "e-mailadres heeft gegeven en ermee instemt dat er contact met hem wordt opgenomen. "
        "Vul nooit gegevens in die de bezoeker niet letterlijk zelf heeft gegeven."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Naam zoals de bezoeker die gaf."},
            "email": {"type": "string", "description": "E-mailadres zoals de bezoeker het gaf."},
            "phone": {
                "type": "string",
                "description": "Telefoonnummer, alleen als de bezoeker teruggebeld wil worden en het zelf gaf.",
            },
            "contact_preference": {
                "type": "string",
                "enum": ["email", "telefoon"],
                "description": "Hoe de bezoeker benaderd wil worden.",
            },
            "course_interest": {
                "type": "string",
                "description": "Opleiding(en) waar de bezoeker interesse in heeft, op basis van het gesprek.",
            },
            "motivation": {
                "type": "string",
                "description": "Waarom de bezoeker een opleiding zoekt, kort samengevat uit het gesprek.",
            },
            "objections": {
                "type": "string",
                "description": "Twijfels of bezwaren die de bezoeker noemde (prijs, tijd, niveau, ...).",
            },
        },
        "required": ["name", "email", "contact_preference"],
    },
}

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_FIELD_CHARS = 1000


class InvalidLead(ValueError):
    """Raised with a message the model can relay to the visitor."""


def clean_lead(raw: dict) -> dict:
    """Validate and normalise the tool input. Raises InvalidLead if unusable."""
    lead = {
        key: str(value).strip()[:MAX_FIELD_CHARS]
        for key, value in raw.items()
        if key in SAVE_LEAD_TOOL["input_schema"]["properties"] and value not in (None, "")
    }

    if not lead.get("name"):
        raise InvalidLead("Naam ontbreekt. Vraag de bezoeker naar zijn naam.")
    email = lead.get("email", "").lower()
    if not EMAIL_PATTERN.match(email):
        raise InvalidLead("Het e-mailadres lijkt niet geldig. Vraag de bezoeker het te controleren.")
    lead["email"] = email

    if lead.get("contact_preference") not in ("email", "telefoon"):
        lead["contact_preference"] = "email"
    if lead["contact_preference"] == "telefoon":
        digits = re.sub(r"\D", "", lead.get("phone", ""))
        if len(digits) < 9:
            raise InvalidLead(
                "Voor terugbellen is een geldig telefoonnummer nodig. Vraag de bezoeker erom."
            )
    return lead

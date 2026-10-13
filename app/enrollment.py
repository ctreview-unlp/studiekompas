"""
Enrollment buttons only appear when the visitor wants to enroll.

The system prompt tells the model to show an enrollment (checkout) link
only after the visitor says they want to enroll, but it doesn't always
comply, and an unrequested "Inschrijven" button reads as selling, against
the advisor's core rule. This enforces it: checkout links are removed from
a reply unless the visitor's latest message shows enrollment intent, or
says yes to the advisor asking whether they want to enroll.
"""

import re

# Enrollment links go to the checkout (unlp.plugandpay.nl/checkout/...).
CHECKOUT_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]*(?:plugandpay\.nl|/checkout/)[^)\s]*)\)")

ENROLL_INTENT = re.compile(
    r"\b(inschrijv\w*|schrijf\s+(me|mij|ik)\b[^.?!]*\bin\b|aanmeld\w*|aanmelding\w*"
    r"|meld\s+(me|mij|ik)\b[^.?!]*\baan\b|boeken\b|reserve\w*|registr\w*"
    r"|betal\w*|doe\s+mee|meedoen|inschrijflink|aanmeldlink)",
    re.IGNORECASE,
)
# "ik wil me nog niet inschrijven", "aanmelden doe ik later niet"
NO_INTENT = re.compile(
    r"\b(niet|geen|nooit)\b[^.?!]{0,25}\b(inschrijv|aanmeld|schrijf|meld|boek)"
    r"|\b(inschrijv|aanmeld)\w*\s+(nog\s+)?niet\b",
    re.IGNORECASE,
)
ASKED_ABOUT_ENROLLING = re.compile(r"\b(inschrijv\w*|aanmeld\w*|schrijven)\b[^?]*\?", re.IGNORECASE)
AFFIRMATIVE = re.compile(
    r"^\s*(ja|jazeker|jawel|graag|zeker|prima|oké|ok|okay|doe maar|klopt|yes|top|is goed|lijkt me goed|dat wil ik)\b",
    re.IGNORECASE,
)


def wants_to_enroll(history: list[dict]) -> bool:
    """
    True if the latest visitor message asks to enroll, or agrees after the
    advisor asked whether they want to enroll. `history` ends with that
    visitor message.
    """
    users = [i for i, turn in enumerate(history) if turn.get("role") == "user"]
    if not users:
        return False
    message = history[users[-1]].get("content", "")
    if NO_INTENT.search(message):
        return False
    if ENROLL_INTENT.search(message):
        return True
    previous = next(
        (t.get("content", "") for t in reversed(history[:users[-1]]) if t.get("role") == "assistant"),
        "",
    )
    return bool(AFFIRMATIVE.search(message) and ASKED_ABOUT_ENROLLING.search(previous))


# "Via de knop hieronder kun je je inschrijving afronden." points at the removed button.
BUTTON_REFERENCE = re.compile(
    r"[^.!?\n]*\bknop\w*\b[^.!?\n]*\b(inschrijv\w*|aanmeld\w*|afronden|inschrijving)\b[^.!?\n]*[.!?]\s*",
    re.IGNORECASE,
)


def remove_checkout_links(reply: str) -> str:
    """Drop checkout buttons and sentences pointing at them; a checkout link
    inside a sentence keeps its text."""
    lines = []
    for line in reply.split("\n"):
        without = CHECKOUT_LINK.sub("", line)
        if CHECKOUT_LINK.search(line) and not re.search(r"\w", without):
            continue  # the line was only a button
        lines.append(BUTTON_REFERENCE.sub("", CHECKOUT_LINK.sub(r"\1", line)).rstrip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def enforce_enrollment_intent(reply: str, history: list[dict]) -> tuple[str, bool]:
    """Returns the reply, without checkout links unless the visitor wants to enroll,
    and whether any were removed."""
    if not CHECKOUT_LINK.search(reply) or wants_to_enroll(history):
        return reply, False
    return remove_checkout_links(reply), True

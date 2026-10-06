import pytest

from app.leads import InvalidLead, clean_lead
from app.notify import build_lead_email


def test_clean_lead_normalises_email_and_defaults_preference():
    lead = clean_lead({"name": " Sanne ", "email": " Sanne@Example.NL", "unknown": "x"})
    assert lead == {"name": "Sanne", "email": "sanne@example.nl", "contact_preference": "email"}


@pytest.mark.parametrize("raw", [
    {"name": "", "email": "a@b.nl"},
    {"name": "Sanne", "email": "not-an-email"},
    {"name": "Sanne", "email": "a@b.nl", "contact_preference": "telefoon"},
    {"name": "Sanne", "email": "a@b.nl", "contact_preference": "telefoon", "phone": "123"},
])
def test_clean_lead_rejects_unusable_input(raw):
    with pytest.raises(InvalidLead):
        clean_lead(raw)


def test_clean_lead_accepts_callback_with_phone():
    lead = clean_lead({"name": "Sanne", "email": "a@b.nl", "contact_preference": "telefoon",
                       "phone": "06 12345678"})
    assert lead["phone"] == "06 12345678"


def test_lead_email_contains_details_summary_and_link():
    msg = build_lead_email(
        {"name": "Sanne", "email": "a@b.nl", "contact_preference": "telefoon", "phone": "0612345678"},
        {"summary": "Wil coach worden.", "recommended_course": "NLP Practitioner",
         "recommended_step": "advice_call"},
        "https://example.com/admin/conversations/1",
    )
    body = msg.get_content()
    assert "Sanne" in msg["Subject"]
    assert msg["Reply-To"] == "a@b.nl"
    assert "teruggebeld" in body and "0612345678" in body
    assert "Wil coach worden." in body and "Adviesgesprek" in body
    assert "https://example.com/admin/conversations/1" in body

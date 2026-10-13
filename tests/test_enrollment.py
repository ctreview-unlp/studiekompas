from app.enrollment import enforce_enrollment_intent

CHECKOUT = "https://unlp.plugandpay.nl/checkout/nlp-practitioner-intensief-rotterdam-30-03-2027"
REPLY = (
    "Op 30 maart 2027 start de Practitioner Intensief in Rotterdam.\n\n"
    f"[Inschrijven voor 30 maart 2027]({CHECKOUT})\n\n"
    "Via de knop hierboven kun je je inschrijving direct afronden. Past dat bij je?"
)


def conversation(*turns):
    roles = ["user", "assistant"]
    return [{"role": roles[i % 2], "content": t} for i, t in enumerate(turns)]


def test_button_removed_without_enrollment_intent():
    reply, removed = enforce_enrollment_intent(REPLY, conversation("Is er in maart iets in Rotterdam?"))
    assert removed
    assert "plugandpay" not in reply and "knop" not in reply
    assert reply.endswith("Past dat bij je?")


def test_button_kept_when_visitor_wants_to_enroll():
    for message in ["Ik wil me inschrijven voor 30 maart", "Hoe meld ik me aan?", "Waar kan ik betalen?",
                    "Schrijf me maar in"]:
        reply, removed = enforce_enrollment_intent(REPLY, conversation(message))
        assert not removed and CHECKOUT in reply, message


def test_button_kept_when_visitor_says_yes_to_enrolling():
    history = conversation(
        "Past 30 maart in Rotterdam?",
        "Ja, die start op 30 maart. Wil je je hiervoor inschrijven, of heb je eerst nog vragen?",
        "Ja graag",
    )
    assert not enforce_enrollment_intent(REPLY, history)[1]


def test_yes_to_something_else_is_not_intent():
    history = conversation("Ik zoek iets in Rotterdam", "Zoek je iets in het weekend?", "Ja")
    assert enforce_enrollment_intent(REPLY, history)[1]


def test_negated_intent_removes_button():
    for message in ["Ik wil me nog niet inschrijven", "Aanmelden niet, eerst nadenken"]:
        assert enforce_enrollment_intent(REPLY, conversation(message))[1], message


def test_other_links_untouched_and_inline_checkout_keeps_text():
    other = "Mail ons gerust.\n\n[Mail UNLP](mailto:info@unlp.nl)"
    assert enforce_enrollment_intent(other, conversation("Hoi")) == (other, False)
    inline = f"Je kunt je [hier inschrijven]({CHECKOUT}) als je wilt."
    reply, removed = enforce_enrollment_intent(inline, conversation("Wat kost het?"))
    assert removed and reply == "Je kunt je hier inschrijven als je wilt."

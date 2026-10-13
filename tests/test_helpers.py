from app.course_links import link_course_names
from app.main import trim_history
from app.rate_limit import RateLimiter

COURSES = [
    {"name": "NLP Practitioner", "url": "https://unlp.nl/practitioner"},
    {"name": "NLP Practitioner Intensief", "url": "https://unlp.nl/intensief"},
    {"name": "Systemisch Coachen", "url": "https://unlp.nl/systemisch"},
    {"name": "Teamcoaching", "url": None},
]


def test_every_mentioned_course_is_linked():
    text = "Je kunt kiezen tussen de NLP Practitioner en Systemisch Coachen."
    assert link_course_names(text, COURSES) == (
        "Je kunt kiezen tussen de [NLP Practitioner](https://unlp.nl/practitioner) "
        "en [Systemisch Coachen](https://unlp.nl/systemisch)."
    )


def test_longest_course_name_wins():
    text = "De NLP Practitioner Intensief duurt korter."
    assert link_course_names(text, COURSES) == (
        "De [NLP Practitioner Intensief](https://unlp.nl/intensief) duurt korter."
    )


def test_course_linked_once_and_case_kept():
    text = "De nlp practitioner is fijn. Na de NLP Practitioner kun je verder."
    linked = link_course_names(text, COURSES)
    assert linked.count("](https://unlp.nl/practitioner)") == 1
    assert linked.startswith("De [nlp practitioner](")


def test_existing_links_and_courses_without_url_are_left_alone():
    text = (
        "Bij Teamcoaching of de NLP Practitioner kun je je inschrijven.\n\n"
        "[Inschrijven voor NLP Practitioner](https://unlp.nl/checkout/1)"
    )
    linked = link_course_names(text, COURSES)
    assert "[Teamcoaching]" not in linked
    assert linked.endswith("[Inschrijven voor NLP Practitioner](https://unlp.nl/checkout/1)")
    assert "[NLP Practitioner](https://unlp.nl/practitioner)" in linked


def test_course_already_linked_by_model_is_not_linked_twice():
    text = "Lees over de [NLP Practitioner](https://unlp.nl/practitioner). De NLP Practitioner duurt 7 dagen."
    assert link_course_names(text, COURSES).count("](https://unlp.nl/practitioner)") == 1


def test_certificate_names_and_quoted_labels_are_not_linked():
    text = (
        'Bij de online variant staat als certificering: NLP Practitioner (ABNLP). '
        'Bij de andere staat "NLP Practitioner". De NLP Practitioner duurt 15 dagen.'
    )
    linked = link_course_names(text, COURSES)
    assert "certificering: NLP Practitioner (ABNLP)" in linked
    assert '"NLP Practitioner"' in linked
    # The first mention that really means the course gets the link.
    assert linked.endswith("De [NLP Practitioner](https://unlp.nl/practitioner) duurt 15 dagen.")


def test_trim_history_keeps_recent_turns_and_starts_with_user():
    history = []
    for i in range(10):
        history.append({"role": "user", "content": f"u{i}"})
        history.append({"role": "assistant", "content": f"a{i}"})
    history.append({"role": "user", "content": "latest"})

    trimmed = trim_history(history, 6)

    assert trimmed[0]["role"] == "user"
    assert trimmed[-1]["content"] == "latest"
    assert len(trimmed) <= 6


def test_rate_limiter_blocks_after_limit_and_recovers_after_window():
    limiter = RateLimiter(max_requests=2, window_seconds=60)
    assert limiter.allow("ip", now=0)
    assert limiter.allow("ip", now=1)
    assert not limiter.allow("ip", now=2)
    assert limiter.allow("other-ip", now=2)
    assert limiter.allow("ip", now=61)


def test_prices_are_listed_per_variant():
    from app.course_data import summarize_prices
    offers = [
        {"variant": "Practitioner Intensief (8 dagen)", "price": 2750},
        {"variant": "NLP Practitioner (15 dagen)", "price": 2995},
        {"variant": "Inclusief:", "price": 2995},
        {"variant": "NLP Practitioner Online (15 avonden)", "price": 1795},
    ]
    assert summarize_prices(offers) == (
        "NLP Practitioner Online (15 avonden): € 1795; Practitioner Intensief (8 dagen): € 2750; "
        "NLP Practitioner (15 dagen): € 2995; andere data (zie prijs per datum): € 2995"
    )
    assert summarize_prices([{"variant": "Inclusief:", "price": 1099}]) == "€ 1099"
    assert summarize_prices([]) is None


def test_every_option_in_a_variant_list_is_linked():
    courses = [
        {"name": "NLP Practitioner", "url": "https://unlp.nl/practitioner"},
        {"name": "NLP Practitioner Intensief", "url": "https://unlp.nl/intensief"},
        {"name": "NLP Practitioner Online", "url": "https://unlp.nl/online"},
    ]
    text = (
        "De NLP Practitioner heeft meerdere varianten, elk met een eigen prijs:\n\n"
        "NLP Practitioner Online (15 avonden): € 1795\n"
        "Practitioner Intensief (8 dagen): € 2750\n"
        "NLP Practitioner (15 dagen): € 2995"
    )
    assert link_course_names(text, courses).split("\n") == [
        "De [NLP Practitioner](https://unlp.nl/practitioner) heeft meerdere varianten, elk met een eigen prijs:",
        "",
        "[NLP Practitioner Online](https://unlp.nl/online) (15 avonden): € 1795",
        "[Practitioner Intensief](https://unlp.nl/intensief) (8 dagen): € 2750",
        "[NLP Practitioner](https://unlp.nl/practitioner) (15 dagen): € 2995",
    ]


def test_everyday_phrases_are_not_mistaken_for_courses():
    courses = [{"name": "NLP voor Jongeren", "url": "https://unlp.nl/jongeren"}]
    assert link_course_names("We hebben ook trainingen voor jongeren.", courses) == (
        "We hebben ook trainingen voor jongeren."
    )
    assert "[NLP voor Jongeren](" in link_course_names("Bekijk NLP voor Jongeren.", courses)

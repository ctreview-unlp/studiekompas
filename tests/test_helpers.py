from app.main import append_missing_info_button, trim_history
from app.rate_limit import RateLimiter

COURSES = [
    {"name": "NLP Practitioner", "url": "https://unlp.nl/practitioner"},
    {"name": "NLP Coachopleiding", "url": "https://unlp.nl/coach"},
]


def test_info_button_added_on_first_mention():
    reply = append_missing_info_button("De NLP Practitioner is een goede start.", COURSES, set())
    assert reply.endswith("[Bekijk de opleiding](https://unlp.nl/practitioner)")


def test_info_button_not_added_twice_for_same_course():
    shown = set()
    append_missing_info_button("De NLP Practitioner past bij je.", COURSES, shown)
    reply = append_missing_info_button("Bij de NLP Practitioner leer je veel.", COURSES, shown)
    assert "](" not in reply


def test_info_button_skipped_when_reply_already_has_a_button():
    text = "Schrijf je in voor de NLP Practitioner. [Inschrijven](https://unlp.nl/inschrijven)"
    assert append_missing_info_button(text, COURSES, set()) == text


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

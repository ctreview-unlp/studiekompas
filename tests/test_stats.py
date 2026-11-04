from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.admin as admin
import app.main as main
import app.stats as stats
from app.rate_limit import RateLimiter
from app.summarize import summarize_conversation

STATS = {
    "totals": {"opened": 12, "conversations": 8, "questions": 30, "median_questions": 2.5, "leads": 2,
               "unlabelled": 3, "last_used": datetime(2026, 11, 3, 9, 0, tzinfo=timezone.utc),
               "first_seen": datetime(2026, 10, 1, tzinfo=timezone.utc)},
    "weekly": [{"week": date(2026, 10, 19), "conversations": 1, "opened": 2},
               {"week": date(2026, 11, 2), "conversations": 7, "opened": 10}],
    "topics": [{"topic": "prijs", "n": 4}, {"topic": "data_locatie", "n": 2}],
    "steps": [{"step": "advice_call", "n": 3}],
    "courses": [{"course": "<b>NLP Practitioner</b>", "n": 5}],
}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("STATS_PASSWORD", "cijfers")
    monkeypatch.setenv("ADMIN_PASSWORD", "geheim")
    periods = []
    monkeypatch.setattr(stats, "usage_stats", lambda _db, days: periods.append(days) or STATS)
    monkeypatch.setattr(admin, "login_limiter", RateLimiter(max_requests=100, window_seconds=60))
    client = TestClient(main.app, base_url="https://testserver", follow_redirects=False)
    client.periods = periods
    return client


def login(client, password="cijfers"):
    return client.post("/stats/login", data={"username": "unlp", "password": password, "next": "/stats"})


def test_stats_disabled_without_password(monkeypatch):
    monkeypatch.delenv("STATS_PASSWORD", raising=False)
    assert TestClient(main.app, follow_redirects=False).get("/stats").status_code == 404


def test_stats_requires_its_own_login(client):
    assert client.get("/stats").headers["location"] == "/stats/login?next=/stats"
    assert login(client, password="geheim").status_code == 401  # the admin password doesn't work here
    assert login(client).headers["location"] == "/stats"
    assert client.get("/admin").status_code == 303  # and a stats login doesn't open /admin


def test_stats_page_shows_totals_topics_and_weeks(client):
    login(client)
    res = client.get("/stats")
    assert res.status_code == 200 and res.headers["cache-control"] == "no-store"
    assert client.periods == [90]  # default period
    text = res.text
    assert "Prijs, betaling en financiering" in text and "4 · 50%" in text
    assert "Adviesgesprek" in text and "mediaan 2,5 per gesprek" in text
    assert "3 gesprekken hebben nog geen onderwerp" in text
    assert "1 gesprek · 2 geopend" in text and "week van 26-10-2026" in text  # empty week filled in
    assert "<b>NLP Practitioner</b>" not in text  # escaped


def test_stats_period_choice(client):
    login(client)
    client.get("/stats?periode=alles")
    client.get("/stats?periode=onzin")
    assert client.periods == [None, 90]


def test_summary_keeps_only_known_topics():
    reply = SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=(
        '{"summary": "s", "recommended_course": "", "recommended_step": "none", "persona_guess": "p",'
        ' "topics": ["prijs", "verzonnen", "prijs", "inhoud", "niveau", "loopbaan"]}'
    ))])
    claude = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: reply))
    result = summarize_conversation(claude, "model", [{"role": "user", "content": "hoi"}], [])
    assert result["topics"] == ["prijs", "inhoud", "niveau"]

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import app.admin as admin
import app.main as main
from app.rate_limit import RateLimiter

ROW = {
    "id": 7, "started_at": datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc),
    "summary": "<script>alert(1)</script>", "recommended_course": "NLP Practitioner",
    "recommended_step": "advice_call", "user_messages": 3,
    "lead_name": "Sanne", "lead_email": "a@b.nl",
}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "geheim")
    monkeypatch.setattr(admin, "list_conversations", lambda *a, **k: [ROW])
    monkeypatch.setattr(admin, "login_limiter", RateLimiter(max_requests=100, window_seconds=60))
    # https, so the Secure session cookie is sent back like in production.
    return TestClient(main.app, base_url="https://testserver", follow_redirects=False)


def login(client, password="geheim", next_url="/admin"):
    return client.post("/admin/login", data={"username": "unlp", "password": password, "next": next_url})


def test_admin_disabled_without_password(monkeypatch):
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    client = TestClient(main.app, follow_redirects=False)
    assert client.get("/admin").status_code == 404
    assert client.get("/admin/login").status_code == 404


def test_admin_redirects_to_login_when_logged_out(client):
    res = client.get("/admin/conversations/7")
    assert res.status_code == 303
    assert res.headers["location"] == "/admin/login?next=/admin/conversations/7"


def test_wrong_password_rejected(client):
    res = login(client, password="fout")
    assert res.status_code == 401
    assert "klopt niet" in res.text
    assert client.get("/admin").status_code == 303


def test_login_then_overview_with_escaped_content_and_logout(client):
    res = login(client)
    assert res.status_code == 303 and res.headers["location"] == "/admin"
    cookie = res.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie

    res = client.get("/admin")
    assert res.status_code == 200
    assert res.headers["cache-control"] == "no-store"
    assert "Aanvraag: Sanne" in res.text and "Log uit" in res.text
    assert "<script>alert(1)</script>" not in res.text

    client.post("/admin/logout")
    assert client.get("/admin").status_code == 303


def test_login_never_redirects_off_site(client):
    res = login(client, next_url="https://evil.example.com")
    assert res.headers["location"] == "/admin"


def test_changing_password_ends_sessions(client, monkeypatch):
    login(client)
    monkeypatch.setenv("ADMIN_PASSWORD", "nieuw")
    assert client.get("/admin").status_code == 303


def test_expired_session_rejected(monkeypatch):
    monkeypatch.setenv("ADMIN_SESSION_HOURS", "-1")
    assert not admin.valid_session(admin.make_session("geheim"), "geheim")


def test_login_attempts_are_rate_limited(client, monkeypatch):
    monkeypatch.setattr(admin, "login_limiter", RateLimiter(max_requests=1, window_seconds=60))
    login(client, password="fout")
    assert login(client).status_code == 429

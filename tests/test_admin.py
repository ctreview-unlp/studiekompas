from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import app.admin as admin
import app.main as main

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
    return TestClient(main.app)


def test_admin_disabled_without_password(monkeypatch):
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    assert TestClient(main.app).get("/admin", auth=("unlp", "x")).status_code == 404


def test_admin_requires_correct_password(client):
    assert client.get("/admin").status_code == 401
    assert client.get("/admin", auth=("unlp", "fout")).status_code == 401


def test_admin_lists_conversations_with_escaped_content(client):
    res = client.get("/admin", auth=("unlp", "geheim"))
    assert res.status_code == 200
    assert "Aanvraag: Sanne" in res.text
    assert "<script>alert(1)</script>" not in res.text
    assert "&lt;script&gt;" in res.text

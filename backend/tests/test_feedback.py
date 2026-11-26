"""Feedback: salvataggio, issue GitHub (rete sostituita da un fake) e anti-spam."""

from __future__ import annotations

import datetime as dt
import logging

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import feedback
from app.config import Settings, get_settings
from app.db import Base, Feedback, get_session
from app.main import app


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Client su SQLite temporaneo; ``env.settings`` e ``env.calls`` modificabili dai test."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'fb.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    class Env:
        settings = Settings(github_token="", github_repo="o/r", feedback_max_per_minute=3)
        calls: list[dict] = []
        response: httpx.Response | Exception = httpx.Response(201, json={"html_url": "u"})

        def rows(self):
            with Session() as s:
                return s.query(Feedback).all()

    e = Env()

    def fake_post(url, **kwargs):
        e.calls.append({"url": url, **kwargs})
        if isinstance(e.response, Exception):
            raise e.response
        return e.response

    def override_session():
        with Session() as s:
            yield s

    monkeypatch.setattr(feedback.httpx, "post", fake_post)
    feedback.limiter.clear()
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = lambda: e.settings
    with TestClient(app) as c:
        e.client = c
        yield e
    app.dependency_overrides.clear()
    feedback.limiter.clear()


def _send(e, **body):
    return e.client.post("/v1/feedback", json={"message": "Vorrei gli orari", **body})


def test_saved_without_token_and_no_issue(env):
    r = _send(env, message="  Vorrei gli orari  ", contact=" ", platform="web")
    assert r.status_code == 201
    [row] = env.rows()
    assert (row.message, row.contact, row.platform) == ("Vorrei gli orari", None, "web")
    assert env.calls == []


def test_rejects_empty_message(env):
    assert _send(env, message="    ").status_code == 422


def test_issue_created_without_contact(env):
    env.settings = Settings(github_token="tok", github_repo="o/r")
    msg = "La linea 4 mostra arrivi sbagliati la sera, @qualcuno ```ciao```"
    r = _send(env, message=msg, contact="mia@email.it", platform="android")
    assert r.status_code == 201
    assert env.rows()[0].contact == "mia@email.it"  # resta nel DB
    [call] = env.calls
    assert call["url"] == "https://api.github.com/repos/o/r/issues"
    assert call["headers"]["Authorization"] == "Bearer tok"
    issue = call["json"]
    assert issue["labels"] == ["feedback"]
    assert issue["title"] == "La linea 4 mostra arrivi sbagliati la sera,…"
    assert "mia@email.it" not in issue["body"]
    assert "````text\n" + msg + "\n````" in issue["body"]  # fence più lungo dei backtick
    assert "**Piattaforma:** android" in issue["body"]


@pytest.mark.parametrize(
    "failure", [httpx.Response(403, text="Resource not accessible"), httpx.ConnectTimeout("t")]
)
def test_github_failure_only_logged(env, caplog, failure):
    env.settings = Settings(github_token="tok", github_repo="o/r")
    env.response = failure
    with caplog.at_level(logging.WARNING, logger="app.feedback"):
        r = _send(env)
    assert r.status_code == 201 and r.json() == {"ok": True}
    assert len(env.rows()) == 1
    assert "Issue GitHub per il feedback non creata" in caplog.text
    assert "tok" not in caplog.text


def test_rate_limit_per_ip(env):
    assert [_send(env).status_code for _ in range(4)] == [201, 201, 201, 429]
    assert len(env.rows()) == 3


def test_rate_limit_uses_configured_ip_header(env):
    env.settings = Settings(client_ip_header="cf-connecting-ip", feedback_max_per_minute=1)

    def send(ip):
        return env.client.post(
            "/v1/feedback", json={"message": "ciao ciao"}, headers={"CF-Connecting-IP": ip}
        ).status_code

    assert [send("1.1.1.1"), send("1.1.1.1"), send("2.2.2.2")] == [201, 429, 201]


def test_rate_limiter_window_and_keys():
    lim = feedback.RateLimiter()
    assert all(lim.allow("a", 2, now=t) for t in (0, 1))
    assert not lim.allow("a", 2, now=2)
    assert lim.allow("b", 2, now=2)  # altro IP
    assert lim.allow("a", 2, now=61)  # finestra scorsa


def test_issue_title_and_date():
    assert feedback.issue_title("Ciao") == "Ciao"
    assert feedback.issue_title("uno due tre quattro cinque sei sette otto nove") == (
        "uno due tre quattro cinque sei sette otto…"
    )
    body = feedback.issue_body("x", None, dt.datetime(2026, 11, 26, 22, 30, tzinfo=dt.UTC))
    assert "**Data:** 26/11/2026 23:30" in body and "non indicata" in body

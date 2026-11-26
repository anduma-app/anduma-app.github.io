"""Processo scheduler: con FCM spento la coda push viene svuotata, non accumulata."""

from __future__ import annotations

from app.alerts import PushMessage
from app.config import Settings
from app.worker import create_scheduler


def test_scheduler_without_fcm_drains_queue():
    scheduler = create_scheduler(
        provider=None, settings=Settings(fcm_enabled=False, keepalive_url="")
    )
    jobs = {j.id: j for j in scheduler.get_jobs()}
    assert set(jobs) == {"imminent", "strike", "service_alert", "push"}

    dispatcher = jobs["imminent"].args[1]
    dispatcher.enqueue(PushMessage(device_id=1, title="t", body="b"))
    jobs["push"].func()
    assert dispatcher.pending == []


def test_keepalive_job_only_when_url_set():
    settings = Settings(fcm_enabled=False, keepalive_url="https://x.onrender.com/")
    jobs = {j.id: j for j in create_scheduler(provider=None, settings=settings).get_jobs()}
    assert jobs["keepalive"].args == ("https://x.onrender.com/health",)


def test_keepalive_url_from_render_env(monkeypatch):
    monkeypatch.delenv("TT_KEEPALIVE_URL", raising=False)
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://x.onrender.com")
    assert Settings().keepalive_url == "https://x.onrender.com"


def test_database_url_forces_psycopg_driver():
    for url in ("postgres://u:p@h:5432/db", "postgresql://u:p@h:5432/db"):
        assert Settings(database_url=url).database_url == "postgresql+psycopg://u:p@h:5432/db"
    assert Settings(database_url="sqlite:///./t.db").database_url == "sqlite:///./t.db"

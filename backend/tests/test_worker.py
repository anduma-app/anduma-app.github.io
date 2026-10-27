"""Processo scheduler: con FCM spento la coda push viene svuotata, non accumulata."""

from __future__ import annotations

from app.alerts import PushMessage
from app.config import Settings
from app.worker import create_scheduler


def test_scheduler_without_fcm_drains_queue():
    scheduler = create_scheduler(provider=None, settings=Settings(fcm_enabled=False))
    jobs = {j.id: j for j in scheduler.get_jobs()}
    assert set(jobs) == {"imminent", "strike", "service_alert", "push"}

    dispatcher = jobs["imminent"].args[1]
    dispatcher.enqueue(PushMessage(device_id=1, title="t", body="b"))
    jobs["push"].func()
    assert dispatcher.pending == []

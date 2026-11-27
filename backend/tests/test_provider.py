"""LiveProvider: refresh GTFS/scioperi con backoff e ricostruzione giornaliera (zero rete)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from app.config import Settings
from app.provider import LiveProvider

ZIP = (Path(__file__).parent / "fixtures" / "gtfs_static.zip").read_bytes()


class Downloader:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def __call__(self, _settings):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def day(monkeypatch):
    current = {"d": dt.date(2030, 1, 1)}
    monkeypatch.setattr("app.clock.today", lambda: current["d"])
    return current


def test_gtfs_rebuilt_on_new_day_without_redownload(day):
    dl = Downloader(ZIP)
    p = LiveProvider(Settings(), gtfs_downloader=dl, strikes_downloader=Downloader(""))
    first = p.gtfs()
    assert first.schedule_date == dt.date(2030, 1, 1) and first.routes
    assert p.gtfs() is first  # stesso giorno: nessun lavoro

    day["d"] = dt.date(2030, 1, 2)
    second = p.gtfs()
    assert second is not first and second.schedule_date == dt.date(2030, 1, 2)
    assert dl.calls == 1


def test_gtfs_failure_backs_off_and_keeps_snapshot(day):
    dl = Downloader(ZIP)
    p = LiveProvider(
        Settings(ttl_gtfs_static=0), gtfs_downloader=dl, strikes_downloader=Downloader("")
    )
    good = p.gtfs()
    dl.result = OSError("rete giù")
    assert p.gtfs() is good  # TTL scaduto, download fallito: snapshot precedente
    assert p.gtfs() is good  # entro il backoff: nessun nuovo tentativo
    assert dl.calls == 2


def test_strikes_failure_backs_off_and_keeps_last(day):
    dl = Downloader("<rss/>")
    p = LiveProvider(
        Settings(ttl_strikes=0), gtfs_downloader=Downloader(ZIP), strikes_downloader=dl
    )
    p.strikes_feed()  # primo download, in background
    p._strikes_thread.join(5)
    assert p.strikes_feed() == "<rss/>"
    p._strikes_thread.join(5)
    dl.result = OSError("rete giù")
    assert p.strikes_feed() == "<rss/>"
    p._strikes_thread.join(5)
    assert p.strikes_feed() == "<rss/>"  # entro il backoff: nessun nuovo tentativo
    assert dl.calls == 3


def test_strikes_never_block_the_caller(day):
    import threading

    release = threading.Event()

    def slow(_settings):
        release.wait(5)  # sito MIT che non risponde
        return "<rss/>"

    p = LiveProvider(Settings(), gtfs_downloader=Downloader(ZIP), strikes_downloader=slow)
    assert p.strikes_feed() == ""  # risponde subito con lo snapshot (vuoto)
    assert p.strikes_feed() == ""  # download già in corso: nessun secondo thread
    release.set()
    p._strikes_thread.join(5)
    assert p.strikes_feed() == "<rss/>"

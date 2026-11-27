"""Provider dati: astrazione tra gli endpoint e le sorgenti (rete/cache).

Gli endpoint dipendono da ``DataProvider`` (interfaccia minima). In produzione
si usa ``LiveProvider`` (scarica GTFS + feed RT + CSV con cache TTL); nei test si
inietta un fake che legge le fixture, così nessun test tocca la rete.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import time
from collections.abc import Callable
from typing import Protocol

from . import clock
from .cache import Cache, get_cache
from .config import Settings, get_settings
from .gtfs_static import GtfsStatic, download_zip_bytes
from .mato import stoptimes_request
from .realtime import FeedFetcher
from .scioperi import download_strikes_rss

log = logging.getLogger(__name__)


class DataProvider(Protocol):
    def gtfs(self) -> GtfsStatic: ...
    def vehicle_positions_bytes(self) -> bytes: ...
    def trip_updates_bytes(self) -> bytes: ...
    def alerts_bytes(self) -> bytes: ...
    def mato_stoptimes(self, stop_code: str) -> bytes: ...
    def strikes_feed(self) -> str: ...


class LiveProvider:
    """Provider di produzione: rete + cache TTL. Tollera sorgenti irraggiungibili.

    GTFS statico e scioperi si aggiornano sotto lock (un solo download alla volta).
    Se il download fallisce si continua a servire l'ultimo snapshot e si ritenta
    dopo ``retry_backoff_s``, senza bloccare ogni richiesta su un timeout.
    L'indice orari del GTFS si ricostruisce dallo ZIP in memoria a ogni cambio di
    data a Torino, senza riscaricarlo.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        gtfs_downloader: Callable[[Settings], bytes] = download_zip_bytes,
        strikes_downloader: Callable[[Settings], str] = download_strikes_rss,
    ):
        self._settings = settings or get_settings()
        self._cache: Cache = get_cache(self._settings)
        self._fetcher = FeedFetcher(self._settings, cache=self._cache)
        self._download_gtfs = gtfs_downloader
        self._download_strikes = strikes_downloader

        self._gtfs_lock = threading.Lock()
        self._gtfs: GtfsStatic | None = None
        self._gtfs_zip: bytes | None = None
        self._gtfs_next_download: float = 0.0
        self.gtfs_loaded_at: float | None = None

        self._strikes_lock = threading.Lock()
        self._strikes: str = ""
        self._strikes_next_download: float = 0.0

    # ------------------------------------------------------------------ GTFS
    def gtfs(self) -> GtfsStatic:
        if self._gtfs is not None and not self._gtfs_stale():
            return self._gtfs
        # Con uno snapshot già pronto non si aspetta chi sta aggiornando.
        if not self._gtfs_lock.acquire(blocking=self._gtfs is None):
            return self._gtfs  # type: ignore[return-value]
        try:
            if self._gtfs is None or self._gtfs_stale():
                self._refresh_gtfs()
        finally:
            self._gtfs_lock.release()
        return self._gtfs if self._gtfs is not None else GtfsStatic()

    def _gtfs_stale(self) -> bool:
        if time.time() >= self._gtfs_next_download:
            return True
        return self._gtfs is not None and self._gtfs.schedule_date != clock.today()

    def _refresh_gtfs(self) -> None:
        now = time.time()
        downloaded = False
        if now >= self._gtfs_next_download:
            try:
                self._gtfs_zip = self._download_gtfs(self._settings)
                self._gtfs_next_download = now + self._settings.ttl_gtfs_static
                downloaded = True
                log.info("GTFS statico scaricato (%d byte)", len(self._gtfs_zip))
            except Exception:
                self._gtfs_next_download = now + self._settings.retry_backoff_s
                log.exception("Download GTFS statico fallito: uso lo snapshot precedente")
        if self._gtfs_zip is None:
            return
        today = clock.today()
        if downloaded or self._gtfs is None or self._gtfs.schedule_date != today:
            self._gtfs = _build_gtfs(self._gtfs_zip, today)
            self.gtfs_loaded_at = time.time()

    # ------------------------------------------------------------- feed RT
    def vehicle_positions_bytes(self) -> bytes:
        return self._fetcher.vehicle_positions()

    def trip_updates_bytes(self) -> bytes:
        return self._fetcher.trip_updates()

    def alerts_bytes(self) -> bytes:
        return self._fetcher.alerts()

    def mato_stoptimes(self, stop_code: str) -> bytes:
        s = self._settings
        return self._fetcher.post_json(
            f"mato:{stop_code}",
            s.mato_graphql_url,
            stoptimes_request(stop_code),
            s.ttl_mato_arrivals,
        )

    # -------------------------------------------------------------- scioperi
    def strikes_feed(self) -> str:
        if time.time() < self._strikes_next_download:
            return self._strikes
        if not self._strikes_lock.acquire(blocking=False):
            return self._strikes  # aggiornamento già in corso: servi l'ultimo
        try:
            now = time.time()
            if now >= self._strikes_next_download:
                try:
                    self._strikes = self._download_strikes(self._settings)
                    self._strikes_next_download = now + self._settings.ttl_strikes
                except Exception:
                    self._strikes_next_download = now + self._settings.retry_backoff_s
                    log.exception("Download registro scioperi fallito: uso l'ultimo snapshot")
        finally:
            self._strikes_lock.release()
        return self._strikes

    @property
    def cache(self) -> Cache:
        return self._cache

    def close(self) -> None:
        self._fetcher.close()


def _build_gtfs(data: bytes, today: dt.date) -> GtfsStatic:
    t0 = time.monotonic()
    gtfs = GtfsStatic.from_zip_bytes(data, schedule_for_date=today)
    log.info(
        "Indice GTFS per %s: %d linee, %d corse indicizzate (%.1f s)",
        today,
        len(gtfs.short_name_to_route_ids),
        len(gtfs.schedule),
        time.monotonic() - t0,
    )
    return gtfs


__all__ = ["DataProvider", "LiveProvider"]

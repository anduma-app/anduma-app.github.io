"""GTFS-Realtime: parsing dei tre feed protobuf + fetcher con cache TTL.

I feed sono protobuf binari (NON JSON): si parsano con ``gtfs-realtime-bindings``.
Tutti i campi sono opzionali per spec, quindi si controlla sempre ``HasField``
prima di leggere e si degrada con grazia.

Le funzioni di parsing sono pure (prendono ``bytes`` + ``GtfsStatic``) e quindi
testabili da fixture; il fetch di rete con TTL sta in ``FeedFetcher``.
"""

from __future__ import annotations

import datetime as dt
import logging
import time

import httpx
from fastapi import HTTPException
from google.transit import gtfs_realtime_pb2

from .cache import Cache, InMemoryCache
from .clock import ROME
from .config import Settings, get_settings
from .gtfs_static import GtfsStatic
from .models import Arrival, ServiceAlert, Vehicle

log = logging.getLogger(__name__)


def parse_feed(data: bytes) -> gtfs_realtime_pb2.FeedMessage:
    """Deserializza un payload GTFS-RT in ``FeedMessage``."""
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(data)
    return feed


def _translated(ts: gtfs_realtime_pb2.TranslatedString) -> str | None:
    """Prima traduzione disponibile di una ``TranslatedString``."""
    for tr in ts.translation:
        if tr.text:
            return tr.text
    return None


# --------------------------------------------------------------------- vehicles
def vehicles_for_line(
    feed: gtfs_realtime_pb2.FeedMessage, gtfs: GtfsStatic, line: str
) -> list[Vehicle]:
    """Posizioni dei mezzi di una linea (filtra per i suoi ``route_id``).

    Se il GTFS statico non è caricato non possiamo mappare le linee: si degrada
    restituendo tutti i mezzi. Se invece è caricato, una linea ignota dà lista
    vuota (``wanted`` vuoto → nessun match).
    """
    wanted = set(gtfs.route_ids_for_line(line))
    gtfs_loaded = bool(gtfs.routes)
    out: list[Vehicle] = []
    for entity in feed.entity:
        if not entity.HasField("vehicle"):
            continue
        vp = entity.vehicle
        route_id = vp.trip.route_id if vp.HasField("trip") else None
        trip_id = vp.trip.trip_id if vp.HasField("trip") else None
        # Filtro linea: per route_id (preferito) o, in mancanza, per trip_id→route.
        if gtfs_loaded:
            line_via_trip = gtfs.short_name_for_trip(trip_id)
            if route_id not in wanted and line_via_trip != line:
                continue

        pos = vp.position if vp.HasField("position") else None
        out.append(
            Vehicle(
                vehicle_id=vp.vehicle.id if vp.HasField("vehicle") else None,
                trip_id=trip_id or None,
                headsign=gtfs.headsign_for_trip(trip_id),
                lat=pos.latitude if pos is not None else None,
                lon=pos.longitude if pos is not None else None,
                bearing=(pos.bearing if pos is not None and pos.HasField("bearing") else None),
                speed=(pos.speed if pos is not None and pos.HasField("speed") else None),
                ts=vp.timestamp if vp.HasField("timestamp") else None,
            )
        )
    return out


# --------------------------------------------------------------------- arrivals
def arrivals_for_stop(
    feed: gtfs_realtime_pb2.FeedMessage,
    gtfs: GtfsStatic,
    stop_id: str,
    line: str | None = None,
    now: float | None = None,
) -> list[Arrival]:
    """Arrivi previsti alla fermata dai ``TripUpdate`` (ordinati per ETA).

    GTT indica la fermata con ``stop_sequence`` (non ``stop_id``) e a volte solo
    col ``delay``: si risolve la sequenza in ``stop_id`` via l'indice orari del
    GTFS statico e si calcola l'ETA da orario assoluto o da programmato + delay.

    GTT pubblica previsioni solo per le prossime fermate della corsa. Per le
    fermate successive vale la regola GTFS-RT: il ritardo dell'ultimo
    aggiornamento precedente si propaga lungo la corsa.
    """
    now_ts = int(now if now is not None else time.time())
    out: list[Arrival] = []
    for entity in feed.entity:
        if not entity.HasField("trip_update"):
            continue
        tu = entity.trip_update
        trip_id = tu.trip.trip_id if tu.HasField("trip") else None
        route_id = tu.trip.route_id if tu.HasField("trip") else None
        short = gtfs.short_name_for_route_id(route_id) or gtfs.short_name_for_trip(trip_id)
        if line is not None and short != line:
            continue
        bases = [_schedule_base_ts(d) for d in _service_dates(tu, gtfs, trip_id)]

        times: list[int | None] = []
        covered: set[int] = set()  # stop_sequence con un aggiornamento esplicito
        for stu in tu.stop_time_update:
            if stu.HasField("stop_sequence"):
                covered.add(stu.stop_sequence)
            # Stop diretto se presente, altrimenti risolto da stop_sequence.
            sid = stu.stop_id if (stu.HasField("stop_id") and stu.stop_id) else None
            sched_secs: int | None = None
            if sid is None and stu.HasField("stop_sequence"):
                resolved = gtfs.resolve_seq(trip_id, stu.stop_sequence)
                if resolved is not None:
                    sid, sched_secs = resolved
            if sid == stop_id:
                times.append(_stop_time_ts(stu, bases, sched_secs, now_ts))

        for seq, sched_secs in gtfs.sequences_for_stop(trip_id, stop_id):
            if seq in covered or sched_secs is None:
                continue
            delay = _propagated_delay(tu, seq)
            if delay is not None and bases:
                candidates = [base + sched_secs + delay for base in bases]
                times.append(min(candidates, key=lambda ts: abs(ts - now_ts)))

        for ts in times:
            if ts is None or ts < now_ts:
                continue  # orario ignoto o mezzo già passato
            eta = ts - now_ts
            out.append(
                Arrival(
                    line=short,
                    headsign=gtfs.headsign_for_trip(trip_id),
                    trip_id=trip_id or None,
                    eta_seconds=eta,
                    eta_minutes=round(eta / 60),
                    scheduled_ts=ts,
                )
            )
    out.sort(key=lambda a: a.eta_seconds)
    return out


def _propagated_delay(tu: gtfs_realtime_pb2.TripUpdate, seq: int) -> int | None:
    """Ritardo dell'ultimo aggiornamento con ``stop_sequence`` precedente a ``seq``.

    None se la fermata precede tutti gli aggiornamenti (mezzo già passato) o se
    l'aggiornamento non porta un ``delay``.
    """
    prev = [
        stu
        for stu in tu.stop_time_update
        if stu.HasField("stop_sequence") and stu.stop_sequence < seq
    ]
    if not prev:
        return None
    last = max(prev, key=lambda stu: stu.stop_sequence)
    for event_name in ("departure", "arrival"):
        if last.HasField(event_name) and getattr(last, event_name).HasField("delay"):
            return getattr(last, event_name).delay
    return None


def _service_dates(
    tu: gtfs_realtime_pb2.TripUpdate, gtfs: GtfsStatic, trip_id: str | None
) -> list[dt.date]:
    """Date di servizio candidate per la corsa: ``start_date`` RT se presente,
    altrimenti i giorni (ieri/oggi) in cui l'indice orari la dà attiva."""
    if tu.HasField("trip") and tu.trip.start_date:
        try:
            return [dt.datetime.strptime(tu.trip.start_date, "%Y%m%d").date()]
        except ValueError:
            pass
    dates = gtfs.trip_dates.get(trip_id or "")
    if dates:
        return list(dates)
    return [gtfs.schedule_date] if gtfs.schedule_date is not None else []


def _schedule_base_ts(service_date: dt.date) -> int:
    """Epoch di "mezzogiorno meno 12 h" della data di servizio, la base degli orari
    GTFS: coincide con la mezzanotte tranne nei giorni del cambio d'ora."""
    noon = dt.datetime(service_date.year, service_date.month, service_date.day, 12, tzinfo=ROME)
    return int(noon.timestamp()) - 12 * 3600


def _event_ts(event, bases: list[int], sched_secs: int | None, now_ts: int) -> int | None:
    """Timestamp d'arrivo: assoluto se presente, altrimenti programmato + delay.

    Con più date di servizio candidate si sceglie quella più vicina ad adesso.
    """
    if event.HasField("time") and event.time > 0:
        return event.time
    if event.HasField("delay") and bases and sched_secs is not None:
        candidates = [base + sched_secs + event.delay for base in bases]
        return min(candidates, key=lambda ts: abs(ts - now_ts))
    return None


def _stop_time_ts(
    stu: gtfs_realtime_pb2.TripUpdate.StopTimeUpdate,
    bases: list[int],
    sched_secs: int | None,
    now_ts: int,
) -> int | None:
    """Arrivo (o, in mancanza, partenza): orario assoluto o programmato + delay."""
    if stu.HasField("arrival"):
        ts = _event_ts(stu.arrival, bases, sched_secs, now_ts)
        if ts is not None:
            return ts
    if stu.HasField("departure"):
        ts = _event_ts(stu.departure, bases, sched_secs, now_ts)
        if ts is not None:
            return ts
    return None


# ----------------------------------------------------------------- service alerts
def alert_entities(
    feed: gtfs_realtime_pb2.FeedMessage, gtfs: GtfsStatic, line: str | None = None
) -> list[tuple[str, ServiceAlert]]:
    """Avvisi di servizio col loro ``entity.id`` (stabile, per la deduplica push).

    Opzionalmente filtrati per linea.
    """
    out: list[tuple[str, ServiceAlert]] = []
    for entity in feed.entity:
        if not entity.HasField("alert"):
            continue
        alert = entity.alert
        lines: list[str] = []
        for ie in alert.informed_entity:
            short = gtfs.short_name_for_route_id(ie.route_id or None)
            if short and short not in lines:
                lines.append(short)
        if line is not None and line not in lines:
            continue
        effect = (
            gtfs_realtime_pb2.Alert.Effect.Name(alert.effect) if alert.HasField("effect") else None
        )
        sa = ServiceAlert(
            header=_translated(alert.header_text),
            description=_translated(alert.description_text),
            effect=effect,
            lines=lines,
        )
        out.append((entity.id, sa))
    return out


def service_alerts(
    feed: gtfs_realtime_pb2.FeedMessage, gtfs: GtfsStatic, line: str | None = None
) -> list[ServiceAlert]:
    """Avvisi di servizio GTT; opzionalmente filtrati per linea."""
    return [sa for _id, sa in alert_entities(feed, gtfs, line)]


# ------------------------------------------------------------------- TTL fetcher
# Per quanto si può servire l'ultimo payload valido se la sorgente è giù.
_STALE_TTL_S = 3600


class FeedFetcher:
    """Scarica i feed RT con cache TTL condivisa (un fetch per finestra).

    La cache è iniettabile: in-memory in sviluppo, Redis in produzione (la
    stessa istanza è condivisa, così il polling resta centralizzato).
    """

    def __init__(
        self,
        settings: Settings | None = None,
        client: httpx.Client | None = None,
        cache: Cache | None = None,
    ):
        self._settings = settings or get_settings()
        self._client = client or httpx.Client(
            timeout=self._settings.http_timeout,
            headers={"User-Agent": "Mozilla/5.0 (compatible; Anduma/1.0)"},
        )
        self._cache: Cache = cache or InMemoryCache()

    def _get(self, key: str, url: str, ttl: int) -> bytes:
        hit = self._cache.get(f"rt:{key}")
        if hit is not None:
            return hit
        try:
            resp = self._client.get(url, follow_redirects=True)
            resp.raise_for_status()
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            # Sorgente giù (GTT a volte risponde 500): meglio dati di qualche
            # minuto fa che nessun dato. Si ritenta al giro successivo.
            stale = self._cache.get(f"rt:{key}:last")
            if stale is not None:
                log.warning("Feed RT %s non raggiungibile, uso l'ultimo valido: %s", key, exc)
                return stale
            raise HTTPException(
                status_code=503,
                detail=f"Feed RT non raggiungibile: {exc}",
            ) from exc
        self._cache.set(f"rt:{key}", resp.content, ttl)
        self._cache.set(f"rt:{key}:last", resp.content, _STALE_TTL_S)
        return resp.content

    def post_json(self, key: str, url: str, body: dict, ttl: int) -> bytes:
        """POST JSON con cache TTL e senza ripiego su dati vecchi: gli errori di rete
        risalgono al chiamante, che decide la fonte alternativa."""
        hit = self._cache.get(f"rt:{key}")
        if hit is not None:
            return hit
        resp = self._client.post(url, json=body)
        resp.raise_for_status()
        self._cache.set(f"rt:{key}", resp.content, ttl)
        return resp.content

    def vehicle_positions(self) -> bytes:
        s = self._settings
        return self._get("vehicles", s.rt_vehicle_positions_url, s.ttl_vehicle_positions)

    def trip_updates(self) -> bytes:
        s = self._settings
        return self._get("trips", s.rt_trip_updates_url, s.ttl_trip_updates)

    def alerts(self) -> bytes:
        s = self._settings
        return self._get("alerts", s.rt_alerts_url, s.ttl_alerts)

    def close(self) -> None:
        self._client.close()


__all__ = [
    "parse_feed",
    "vehicles_for_line",
    "arrivals_for_stop",
    "service_alerts",
    "alert_entities",
    "FeedFetcher",
]

"""Motore alert + scheduler.

Due valutazioni periodiche (APScheduler):

- **imminent** (~15 s): per ogni sottoscrizione, legge gli arrivi previsti alla
  fermata per la linea; se l'ETA è entro la soglia e non già notificato per quel
  ``trip_id``, accoda una push.
- **strike** (~1 h): per ogni nuovo sciopero rilevante per Torino, notifica le
  sottoscrizioni ``strike`` (una sola volta per sciopero).

La logica è **idempotente**: la deduplica passa da ``notified_events`` (chiave
``(subscription_id, dedup_key)`` con TTL). Il dispatcher è **disaccoppiato**: qui
si accoda soltanto; l'invio reale (FCM/APNs) arriva in M4. Le funzioni di
valutazione sono pure rispetto a feed/scioperi passati come argomento, quindi
testabili senza rete né invii reali.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from google.transit import gtfs_realtime_pb2
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from .clock import ROME
from .config import Settings, get_settings
from .db import NotifiedEvent, Subscription
from .gtfs_static import GtfsStatic
from .mato import stop_arrivals
from .models import Arrival, Strike
from .realtime import alert_entities, parse_feed
from .scioperi import filter_for_torino, filter_upcoming, parse_date, parse_strikes_rss

log = logging.getLogger(__name__)

# Buffer oltre l'ETA stimato prima che la dedup scada (il mezzo è passato).
_IMMINENT_TTL_BUFFER_S = 120
# Uno sciopero non si rinotifica finché non è passato (date assenti: orizzonte MIT).
_STRIKE_TTL_GRACE_DAYS = 2
_STRIKE_TTL_FALLBACK_DAYS = 400
# Avvisi di servizio: ri-notifica al più una volta a settimana se ancora attivi.
_ALERT_TTL_DAYS = 7


@dataclass
class PushMessage:
    """Notifica da inviare (consumata dal push reale in M4)."""

    device_id: int
    title: str
    body: str
    data: dict[str, str] = field(default_factory=dict)


class Dispatcher(Protocol):
    def enqueue(self, message: PushMessage) -> None: ...


class InProcessDispatcher:
    """Coda in-process: punto di disaccoppiamento prima del push reale (M4)."""

    def __init__(self) -> None:
        self._queue: list[PushMessage] = []

    def enqueue(self, message: PushMessage) -> None:
        self._queue.append(message)

    def drain(self) -> list[PushMessage]:
        """Restituisce e svuota la coda (lo userà il dispatcher push)."""
        items, self._queue = self._queue, []
        return items

    @property
    def pending(self) -> list[PushMessage]:
        return list(self._queue)


def _now_dt(now_ts: float) -> dt.datetime:
    return dt.datetime.fromtimestamp(now_ts, dt.UTC)


def _purge_expired(session: Session, now_dt: dt.datetime) -> None:
    """Rimuove le voci di deduplica scadute: la tabella resta piccola e la chiave riutilizzabile."""
    session.execute(delete(NotifiedEvent).where(NotifiedEvent.expires_at <= now_dt))


def _by_device(subs) -> dict[int, list[Subscription]]:
    grouped: dict[int, list[Subscription]] = defaultdict(list)
    for sub in subs:
        grouped[sub.device_id].append(sub)
    return grouped


def _claim_for_device(
    session: Session,
    subs: list[Subscription],
    key: str,
    now_dt: dt.datetime,
    expires: dt.datetime,
) -> bool:
    """Registra l'evento per tutte le sottoscrizioni del device.

    True se il device non l'aveva ancora ricevuto (va notificato una sola volta,
    anche se ha più sottoscrizioni che lo riguardano).
    """
    fresh = [sub for sub in subs if not _already_notified(session, sub.id, key, now_dt)]
    for sub in fresh:
        session.add(NotifiedEvent(subscription_id=sub.id, dedup_key=key, expires_at=expires))
    return len(fresh) == len(subs)


def _already_notified(
    session: Session, subscription_id: int, dedup_key: str, now_dt: dt.datetime
) -> bool:
    return (
        session.scalar(
            select(NotifiedEvent).where(
                NotifiedEvent.subscription_id == subscription_id,
                NotifiedEvent.dedup_key == dedup_key,
                NotifiedEvent.expires_at > now_dt,
            )
        )
        is not None
    )


# ------------------------------------------------------------------- imminent
# (stop_id, linea, istante) -> arrivi previsti alla fermata.
ArrivalsFn = Callable[[str, str | None, float], list[Arrival]]


def evaluate_imminent(
    session: Session,
    arrivals_fn: ArrivalsFn,
    dispatcher: Dispatcher,
    now: float | None = None,
) -> int:
    """Valuta le sottoscrizioni ``imminent`` sugli arrivi dati. Ritorna gli accodati."""
    now_ts = now if now is not None else time.time()
    now_dt = _now_dt(now_ts)
    _purge_expired(session, now_dt)
    subs = session.scalars(
        select(Subscription).where(Subscription.kind == "imminent", Subscription.active.is_(True))
    ).all()

    enqueued = 0
    for sub in subs:
        if not sub.stop_id:
            continue
        arrivals = arrivals_fn(sub.stop_id, sub.line, now_ts)
        for arr in arrivals:
            if arr.trip_id is None:
                continue
            if sub.threshold_min is not None and arr.eta_minutes > sub.threshold_min:
                continue
            dedup_key = f"imminent:{arr.trip_id}"
            if _already_notified(session, sub.id, dedup_key, now_dt):
                continue
            expires = now_dt + dt.timedelta(seconds=arr.eta_seconds + _IMMINENT_TTL_BUFFER_S)
            session.add(
                NotifiedEvent(subscription_id=sub.id, dedup_key=dedup_key, expires_at=expires)
            )
            line = arr.line or sub.line or "?"
            dispatcher.enqueue(
                PushMessage(
                    device_id=sub.device_id,
                    title=f"Linea {line} in arrivo",
                    body=f"~{arr.eta_minutes} min alla fermata {sub.stop_id}"
                    + (f" → {arr.headsign}" if arr.headsign else ""),
                    data={
                        "kind": "imminent",
                        "line": line,
                        "stop_id": sub.stop_id,
                        "trip_id": arr.trip_id,
                        "eta_seconds": str(arr.eta_seconds),
                    },
                )
            )
            enqueued += 1
    session.commit()
    return enqueued


# --------------------------------------------------------------------- strike
def strike_key(strike: Strike) -> str:
    """Identità stabile di uno sciopero (per la deduplica): il guid MIT se c'è."""
    base = strike.raw.get("guid") or "|".join(
        [
            strike.start_date or "",
            strike.end_date or "",
            strike.area or "",
            strike.sector or "",
        ]
    )
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]
    return f"strike:{digest}"


def _strike_expiry(strike: Strike, now_dt: dt.datetime) -> dt.datetime:
    """Scadenza della deduplica: qualche giorno dopo la fine (o l'inizio) dello sciopero."""
    last = parse_date(strike.end_date) or parse_date(strike.start_date)
    if last is None:
        return now_dt + dt.timedelta(days=_STRIKE_TTL_FALLBACK_DAYS)
    end_of_day = dt.datetime.combine(last + dt.timedelta(days=_STRIKE_TTL_GRACE_DAYS), dt.time())
    return max(end_of_day.replace(tzinfo=ROME), now_dt + dt.timedelta(days=1))


def evaluate_strikes(
    session: Session,
    strikes: list[Strike],
    dispatcher: Dispatcher,
    now: float | None = None,
) -> int:
    """Notifica ogni device con sottoscrizioni ``strike`` una volta per sciopero. Idempotente."""
    now_ts = now if now is not None else time.time()
    now_dt = _now_dt(now_ts)
    _purge_expired(session, now_dt)
    subs = session.scalars(
        select(Subscription).where(Subscription.kind == "strike", Subscription.active.is_(True))
    ).all()

    enqueued = 0
    for strike in strikes:
        key = strike_key(strike)
        expires = _strike_expiry(strike, now_dt)
        for device_id, dsubs in _by_device(subs).items():
            if not _claim_for_device(session, dsubs, key, now_dt, expires):
                continue
            when = strike.start_date or "prossimamente"
            dispatcher.enqueue(
                PushMessage(
                    device_id=device_id,
                    title="Sciopero trasporto pubblico",
                    body=f"Sciopero TPL ({strike.area or 'nazionale'}) — {when}",
                    data={
                        "kind": "strike",
                        "line": dsubs[0].line or "",
                        "area": strike.area or "",
                        "start_date": strike.start_date or "",
                    },
                )
            )
            enqueued += 1
    session.commit()
    return enqueued


# -------------------------------------------------------------- service alerts
def evaluate_service_alerts(
    session: Session,
    feed: gtfs_realtime_pb2.FeedMessage,
    gtfs: GtfsStatic,
    dispatcher: Dispatcher,
    now: float | None = None,
) -> int:
    """Notifica le sottoscrizioni ``line_alert`` per gli avvisi sulle loro linee.

    Deduplica per ``(subscription, entity.id)``: un avviso che persiste non
    rinotifica finché non scade il TTL. Un device riceve una sola push per avviso
    anche se segue più linee coinvolte. Idempotente.
    """
    now_ts = now if now is not None else time.time()
    now_dt = _now_dt(now_ts)
    _purge_expired(session, now_dt)
    expires = now_dt + dt.timedelta(days=_ALERT_TTL_DAYS)
    subs = session.scalars(
        select(Subscription).where(Subscription.kind == "line_alert", Subscription.active.is_(True))
    ).all()
    if not subs:
        return 0

    entities = alert_entities(feed, gtfs)
    enqueued = 0
    for entity_id, alert in entities:
        matching = [sub for sub in subs if sub.line and sub.line in alert.lines]
        key = f"alert:{entity_id}"
        for device_id, dsubs in _by_device(matching).items():
            if not _claim_for_device(session, dsubs, key, now_dt, expires):
                continue
            lines = sorted({sub.line for sub in dsubs if sub.line})
            label = f"Linea {lines[0]}" if len(lines) == 1 else f"Linee {', '.join(lines)}"
            header = alert.header or "Avviso di servizio"
            dispatcher.enqueue(
                PushMessage(
                    device_id=device_id,
                    title=f"{label}: {header}",
                    body=alert.description or header,
                    data={
                        "kind": "line_alert",
                        "line": lines[0],
                        "effect": alert.effect or "",
                    },
                )
            )
            enqueued += 1
    session.commit()
    return enqueued


# ----------------------------------------------------------- scheduler wiring
def run_imminent(provider, dispatcher: Dispatcher, session_factory: sessionmaker[Session]) -> int:
    """Job imminent: arrivi da MATO (ripiego GTT) e valutazione (tollerante a errori)."""

    def arrivals_fn(stop_id: str, line: str | None, now: float) -> list[Arrival]:
        try:
            return stop_arrivals(provider, stop_id, line=line, now=now)
        except Exception:
            log.warning("Job imminent: arrivi non disponibili per %s", stop_id, exc_info=True)
            return []

    with session_factory() as session:
        return evaluate_imminent(session, arrivals_fn, dispatcher)


def run_strikes(provider, dispatcher: Dispatcher, session_factory: sessionmaker[Session]) -> int:
    """Job strike: legge il registro MIT dal provider e valuta (tollerante a errori)."""
    try:
        strikes = filter_upcoming(filter_for_torino(parse_strikes_rss(provider.strikes_feed())))
    except Exception:
        log.warning("Job strike: registro scioperi non disponibile", exc_info=True)
        return 0
    with session_factory() as session:
        return evaluate_strikes(session, strikes, dispatcher)


def run_service_alerts(
    provider, dispatcher: Dispatcher, session_factory: sessionmaker[Session]
) -> int:
    """Job avvisi di linea: legge il feed alert dal provider e valuta (tollerante)."""
    try:
        feed = parse_feed(provider.alerts_bytes())
        gtfs = provider.gtfs()
    except Exception:
        log.warning("Job service_alert: feed avvisi non disponibile", exc_info=True)
        return 0
    with session_factory() as session:
        return evaluate_service_alerts(session, feed, gtfs, dispatcher)


def build_scheduler(
    provider,
    dispatcher: Dispatcher,
    session_factory: sessionmaker[Session],
    settings: Settings | None = None,
    push_processor: Callable[[], object] | None = None,
):
    """Crea (senza avviare) un BackgroundScheduler con i job alert.

    Se ``push_processor`` è fornito (callable a zero argomenti), aggiunge anche un
    job ``push`` che svuota la coda del dispatcher e invia (vedi M4).
    """
    from apscheduler.schedulers.background import BackgroundScheduler

    settings = settings or get_settings()
    scheduler = BackgroundScheduler(timezone=ROME)
    scheduler.add_job(
        run_imminent,
        "interval",
        seconds=settings.imminent_interval_s,
        args=[provider, dispatcher, session_factory],
        id="imminent",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        run_strikes,
        "interval",
        seconds=settings.strike_interval_s,
        args=[provider, dispatcher, session_factory],
        id="strike",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        run_service_alerts,
        "interval",
        seconds=settings.service_alert_interval_s,
        args=[provider, dispatcher, session_factory],
        id="service_alert",
        max_instances=1,
        coalesce=True,
    )
    if push_processor is not None:
        scheduler.add_job(
            push_processor,
            "interval",
            seconds=settings.push_interval_s,
            id="push",
            max_instances=1,
            coalesce=True,
        )
    return scheduler


__all__ = [
    "PushMessage",
    "Dispatcher",
    "InProcessDispatcher",
    "evaluate_imminent",
    "evaluate_strikes",
    "evaluate_service_alerts",
    "strike_key",
    "run_imminent",
    "run_strikes",
    "build_scheduler",
]

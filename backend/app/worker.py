"""Processo scheduler: motore alert + invio push, separato dalle repliche API.

In produzione gira in **una sola** istanza (``python -m app.worker``), così i job
non si duplicano quando l'API ha più worker o repliche. In sviluppo lo stesso
scheduler può girare dentro il processo API con ``TT_SCHEDULER_ENABLED=true``.
"""

from __future__ import annotations

import logging
import signal
import threading

from .alerts import InProcessDispatcher, build_scheduler
from .config import Settings, get_settings
from .db import SessionLocal
from .provider import DataProvider, LiveProvider
from .push import build_push_service, make_push_processor

log = logging.getLogger(__name__)


def configure_logging(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def create_scheduler(provider: DataProvider, settings: Settings | None = None):
    """Scheduler (non avviato) con i job alert e lo svuotamento della coda push."""
    settings = settings or get_settings()
    dispatcher = InProcessDispatcher()
    push_service = build_push_service(settings)
    if push_service is not None:
        push_processor = make_push_processor(push_service, dispatcher, SessionLocal)
    else:

        def push_processor() -> None:
            # FCM spento: la coda non deve crescere senza limite.
            dropped = dispatcher.drain()
            if dropped:
                log.info("FCM disabilitato: %d notifiche non inviate", len(dropped))

    return build_scheduler(
        provider, dispatcher, SessionLocal, settings, push_processor=push_processor
    )


def main() -> None:
    settings = get_settings()
    configure_logging(settings)
    provider = LiveProvider(settings)
    scheduler = create_scheduler(provider, settings)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    scheduler.start()
    log.info("Scheduler avviato (FCM %s)", "attivo" if settings.fcm_enabled else "spento")
    stop.wait()
    scheduler.shutdown(wait=True)
    provider.close()


if __name__ == "__main__":
    main()

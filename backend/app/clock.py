"""Ora locale di Torino: date di servizio e "oggi" sono sempre Europe/Rome.

Il server (container) gira spesso in UTC: ``date.today()`` sbaglierebbe giorno
tra mezzanotte e l'una/le due. Tutto il codice passa da qui, e i test possono
sostituire ``today`` senza dipendere dall'orologio.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

ROME = ZoneInfo("Europe/Rome")


def today() -> dt.date:
    return dt.datetime.now(ROME).date()


__all__ = ["ROME", "today"]

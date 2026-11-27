"""Arrivi in fermata da Muoversi a Torino (5T), con ripiego sul feed GTT.

5T calcola le previsioni con un proprio sistema dalle posizioni dei mezzi: oltre
le prime fermate sono più accurate del feed GTT, che pubblica previsioni solo per
le fermate più vicine (poi si può solo propagare l'ultimo ritardo).

La sorgente è il GraphQL di OpenTripPlanner usato da muoversiatorino.it: non è
documentato e 5T lo pubblica senza licenza, quindi per l'art. 52 c. 2 del CAD vale
come dato aperto (CC BY 4.0): va citata la fonte. Se MATO non risponde o non
conosce la fermata si usano i trip update GTT.
"""

from __future__ import annotations

import json
import logging
import time

from .gtfs_static import GtfsStatic
from .models import Arrival
from .realtime import arrivals_for_stop, parse_feed

log = logging.getLogger(__name__)

# Passaggi della fermata nelle prossime due ore. La fermata MATO è "gtt:<palina>".
STOPTIMES_QUERY = """
query ($id: String!) {
  stop(id: $id) {
    stoptimesWithoutPatterns(numberOfDepartures: 50, timeRange: 7200) {
      realtime
      realtimeState
      realtimeArrival
      serviceDay
      trip { gtfsId tripHeadsign route { shortName } }
    }
  }
}
"""


def stoptimes_request(stop_code: str) -> dict:
    """Corpo JSON della richiesta GraphQL per la palina ``stop_code``."""
    return {"query": STOPTIMES_QUERY, "variables": {"id": f"gtt:{stop_code}"}}


def parse_stoptimes(
    payload: bytes, gtfs: GtfsStatic, line: str | None = None, now: float | None = None
) -> list[Arrival] | None:
    """Arrivi in tempo reale dalla risposta MATO, ordinati per ETA.

    None se la risposta non è utilizzabile (errori GraphQL o fermata ignota a MATO):
    il chiamante ripiega sul feed GTT. Si tengono solo i passaggi in tempo reale non
    soppressi, come per il feed GTT.
    """
    data = json.loads(payload)
    stop = (data.get("data") or {}).get("stop")
    if data.get("errors") or stop is None:
        return None
    now_ts = int(now if now is not None else time.time())
    out: list[Arrival] = []
    for st in stop.get("stoptimesWithoutPatterns") or []:
        if not st.get("realtime") or st.get("realtimeState") == "CANCELED":
            continue
        if st.get("serviceDay") is None or st.get("realtimeArrival") is None:
            continue
        ts = st["serviceDay"] + st["realtimeArrival"]
        if ts < now_ts:
            continue
        trip = st.get("trip") or {}
        gtfs_id = trip.get("gtfsId") or ""
        trip_id = gtfs_id.split(":", 1)[1] if ":" in gtfs_id else gtfs_id or None
        short = gtfs.short_name_for_trip(trip_id) or (trip.get("route") or {}).get("shortName")
        if line is not None and short != line:
            continue
        eta = ts - now_ts
        out.append(
            Arrival(
                line=short,
                headsign=gtfs.headsign_for_trip(trip_id) or trip.get("tripHeadsign"),
                trip_id=trip_id,
                eta_seconds=eta,
                eta_minutes=round(eta / 60),
                scheduled_ts=ts,
            )
        )
    out.sort(key=lambda a: a.eta_seconds)
    return out


def stop_arrivals(
    provider, stop_id: str, line: str | None = None, now: float | None = None
) -> list[Arrival]:
    """Arrivi alla fermata: MATO se disponibile, altrimenti trip update GTT."""
    gtfs = provider.gtfs()
    stop = gtfs.stop(stop_id)
    if stop is not None and stop.code:
        try:
            arrivals = parse_stoptimes(provider.mato_stoptimes(stop.code), gtfs, line, now)
            if arrivals is not None:
                return arrivals
            log.info("Fermata %s (palina %s) ignota a MATO: uso il feed GTT", stop_id, stop.code)
        except Exception as exc:
            log.warning("Arrivi MATO non disponibili per la palina %s: %s", stop.code, exc)
    feed = parse_feed(provider.trip_updates_bytes())
    return arrivals_for_stop(feed, gtfs, stop_id, line=line, now=now)


__all__ = ["parse_stoptimes", "stop_arrivals", "stoptimes_request"]

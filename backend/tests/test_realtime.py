"""Test del parsing dei tre feed GTFS-RT (da fixture protobuf, zero rete)."""

from __future__ import annotations

import pytest

from app import realtime
from app.gtfs_static import GtfsStatic

# Stesso istante usato nel generatore di fixture.
FUTURE_TS = 1893456000


def test_vehicles_filtered_by_line(gtfs: GtfsStatic, vehicle_positions_bytes: bytes):
    feed = realtime.parse_feed(vehicle_positions_bytes)
    v10 = realtime.vehicles_for_line(feed, gtfs, "10")
    # Due mezzi di linea 10 (T1 con posizione, T2 senza posizione).
    ids = {v.vehicle_id for v in v10}
    assert ids == {"BUS001", "BUS002"}

    v55 = realtime.vehicles_for_line(feed, gtfs, "55")
    assert {v.vehicle_id for v in v55} == {"BUS055"}


def test_vehicle_position_fields_and_graceful_degrade(
    gtfs: GtfsStatic, vehicle_positions_bytes: bytes
):
    feed = realtime.parse_feed(vehicle_positions_bytes)
    by_id = {v.vehicle_id: v for v in realtime.vehicles_for_line(feed, gtfs, "10")}

    full = by_id["BUS001"]
    # I float GTFS-RT sono float32: confronto con tolleranza.
    assert full.lat == pytest.approx(45.0701) and full.lon == pytest.approx(7.6601)
    assert full.bearing == 90.0 and round(full.speed, 1) == 8.5
    assert full.headsign == "Corso Settembrini"
    assert full.ts == FUTURE_TS

    # Mezzo senza posizione: campi a None, nessun crash.
    no_pos = by_id["BUS002"]
    assert no_pos.lat is None and no_pos.lon is None
    assert no_pos.bearing is None and no_pos.speed is None


def test_arrivals_at_stop_all_lines(gtfs: GtfsStatic, trip_updates_bytes: bytes):
    feed = realtime.parse_feed(trip_updates_bytes)
    arrivals = realtime.arrivals_for_stop(feed, gtfs, "350", now=FUTURE_TS)
    # Linea 55 (+120s) prima della 10 (+240s); il trip senza orario è scartato.
    assert [a.line for a in arrivals] == ["55", "10"]
    assert arrivals[0].eta_seconds == 120 and arrivals[0].eta_minutes == 2
    assert arrivals[1].eta_seconds == 240 and arrivals[1].headsign == "Corso Settembrini"


def test_arrivals_filtered_by_line(gtfs: GtfsStatic, trip_updates_bytes: bytes):
    feed = realtime.parse_feed(trip_updates_bytes)
    arrivals = realtime.arrivals_for_stop(feed, gtfs, "350", line="10", now=FUTURE_TS)
    assert len(arrivals) == 1 and arrivals[0].line == "10"


def test_arrivals_drop_past_departures(gtfs: GtfsStatic, trip_updates_bytes: bytes):
    feed = realtime.parse_feed(trip_updates_bytes)
    # 'now' dopo tutti gli arrivi: nessun arrivo futuro.
    assert realtime.arrivals_for_stop(feed, gtfs, "350", now=FUTURE_TS + 10_000) == []


def test_arrivals_resolve_stop_sequence_and_delay():
    """Feed in stile GTT: niente stop_id, solo stop_sequence + delay → risolto."""
    import datetime as dt
    from zoneinfo import ZoneInfo

    from google.transit import gtfs_realtime_pb2

    # GtfsStatic isolato: T1 → route R10A ("10"); indice orari seq 5 → fermata 350.
    gtfs = GtfsStatic(
        routes={"R10A": {"route_id": "R10A", "route_short_name": "10"}},
        short_name_to_route_ids={"10": ["R10A"]},
        trips={"T1": {"trip_id": "T1", "route_id": "R10A", "trip_headsign": "Test"}},
        schedule={"T1": {5: ("350", 12 * 3600)}},
        schedule_date=dt.date(2030, 1, 1),
    )
    base = dt.datetime(2030, 1, 1, tzinfo=ZoneInfo("Europe/Rome")).timestamp()

    feed = gtfs_realtime_pb2.FeedMessage()
    e = feed.entity.add()
    e.id = "tu1"
    tu = e.trip_update
    tu.trip.trip_id = "T1"  # route_id assente, come in GTT → risolto via trip
    stu = tu.stop_time_update.add()
    stu.stop_sequence = 5  # nessuno stop_id
    stu.arrival.delay = 120  # 2 min di ritardo sul programmato

    # now = 11:55 locale → arrivo previsto 12:02 → ~7 min.
    now = base + 12 * 3600 - 5 * 60
    arrivals = realtime.arrivals_for_stop(feed, gtfs, "350", now=now)
    assert len(arrivals) == 1
    assert arrivals[0].line == "10"  # T1 → R10A → "10"
    assert arrivals[0].eta_seconds == 120 + 5 * 60  # delay + (12:00 - 11:55)


def test_service_alerts(gtfs: GtfsStatic, alerts_bytes: bytes):
    feed = realtime.parse_feed(alerts_bytes)
    all_alerts = realtime.service_alerts(feed, gtfs)
    assert len(all_alerts) == 2

    only10 = realtime.service_alerts(feed, gtfs, line="10")
    assert len(only10) == 1
    a = only10[0]
    assert a.header == "Deviazione linea 10"
    assert a.description == "Lavori in corso in Corso Regina"
    assert a.effect == "DETOUR"
    assert a.lines == ["10"]


def _delay_only_feed(trip_id: str, seq: int, delay: int, start_date: str | None = None):
    from google.transit import gtfs_realtime_pb2

    feed = gtfs_realtime_pb2.FeedMessage()
    tu = feed.entity.add(id="tu").trip_update
    tu.trip.trip_id = trip_id
    if start_date:
        tu.trip.start_date = start_date
    stu = tu.stop_time_update.add()
    stu.stop_sequence = seq
    stu.arrival.delay = delay
    return feed


def _gtfs_one_trip(sched_secs: int, **kw) -> GtfsStatic:
    return GtfsStatic(
        routes={"R10A": {"route_id": "R10A", "route_short_name": "10"}},
        short_name_to_route_ids={"10": ["R10A"]},
        trips={"T1": {"trip_id": "T1", "route_id": "R10A"}},
        schedule={"T1": {5: ("350", sched_secs)}},
        **kw,
    )


def _rome_ts(*args) -> float:
    import datetime as dt

    from app.clock import ROME

    return dt.datetime(*args, tzinfo=ROME).timestamp()


def test_arrivals_use_rt_start_date_for_after_midnight_trip():
    """Corsa di ieri alle 24:30 (orario GTFS), letta all'00:20 di oggi."""
    import datetime as dt

    gtfs = _gtfs_one_trip(24 * 3600 + 30 * 60, schedule_date=dt.date(2030, 1, 2))
    feed = _delay_only_feed("T1", 5, 60, start_date="20300101")
    now = _rome_ts(2030, 1, 2, 0, 20)
    [a] = realtime.arrivals_for_stop(feed, gtfs, "350", now=now)
    assert a.scheduled_ts == _rome_ts(2030, 1, 2, 0, 31)


def test_arrivals_without_start_date_pick_closest_service_day():
    """Senza start_date: tra ieri e oggi vince la data con l'orario più vicino ad adesso."""
    import datetime as dt

    d1, d2 = dt.date(2030, 1, 1), dt.date(2030, 1, 2)
    gtfs = _gtfs_one_trip(9 * 3600, schedule_date=d2, trip_dates={"T1": (d1, d2)})
    feed = _delay_only_feed("T1", 5, 0)
    [a] = realtime.arrivals_for_stop(feed, gtfs, "350", now=_rome_ts(2030, 1, 2, 8, 50))
    assert a.eta_seconds == 600


def test_arrivals_correct_on_dst_change_day():
    """Il 25/10/2026 torna l'ora solare: gli orari GTFS partono da mezzogiorno − 12 h."""
    import datetime as dt

    gtfs = _gtfs_one_trip(12 * 3600, schedule_date=dt.date(2026, 10, 25))
    feed = _delay_only_feed("T1", 5, 0, start_date="20261025")
    now = _rome_ts(2026, 10, 25, 11, 50)
    [a] = realtime.arrivals_for_stop(feed, gtfs, "350", now=now)
    assert a.scheduled_ts == _rome_ts(2026, 10, 25, 12, 0)
    assert a.eta_seconds == 600


def test_arrivals_propagate_delay_to_later_stops():
    """GTT aggiorna solo le prossime fermate: il ritardo si propaga alle successive."""
    import datetime as dt

    gtfs = GtfsStatic(
        routes={"R10A": {"route_id": "R10A", "route_short_name": "10"}},
        trips={"T1": {"trip_id": "T1", "route_id": "R10A"}},
        schedule={
            "T1": {5: ("100", 9 * 3600), 6: ("200", 9 * 3600 + 120), 9: ("350", 9 * 3600 + 600)}
        },
        schedule_date=dt.date(2030, 1, 2),
    )
    feed = _delay_only_feed("T1", 5, 180, start_date="20300102")  # 3 min di ritardo alla seq 5
    now = _rome_ts(2030, 1, 2, 9, 0)
    [a] = realtime.arrivals_for_stop(feed, gtfs, "350", now=now)
    assert a.eta_seconds == 600 + 180
    # Fermata già superata (prima del primo aggiornamento): nessun arrivo.
    gtfs.schedule["T1"][1] = ("50", 8 * 3600)
    assert realtime.arrivals_for_stop(feed, gtfs, "50", now=now) == []

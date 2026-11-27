"""Arrivi da Muoversi a Torino (5T) e ripiego sul feed GTT (fixture, zero rete)."""

from __future__ import annotations

from app.gtfs_static import GtfsStatic
from app.mato import parse_stoptimes, stop_arrivals, stoptimes_request

from .conftest import FIX, FakeProvider

# 2030-01-01 01:00 a Torino; serviceDay della fixture = mezzanotte di quel giorno.
FUTURE_TS = 1893456000
MATO = (FIX / "mato_stoptimes.json").read_bytes()


class MatoProvider(FakeProvider):
    """Fixture GTT + risposta MATO salvata; registra le palina richieste."""

    def __init__(self, gtfs: GtfsStatic, payload: bytes = MATO):
        super().__init__(gtfs)
        self._payload = payload
        self.requested: list[str] = []

    def mato_stoptimes(self, stop_code: str) -> bytes:
        self.requested.append(stop_code)
        return self._payload


def test_request_uses_stop_code():
    assert stoptimes_request("350")["variables"] == {"id": "gtt:350"}


def test_parse_keeps_only_future_realtime(gtfs: GtfsStatic):
    arrivals = parse_stoptimes(MATO, gtfs, now=FUTURE_TS)
    # Esclusi: corsa da orario (T2), soppressa (X1), già passata (X2).
    assert [(a.line, a.eta_seconds) for a in arrivals] == [("55", 60), ("10", 300), ("4", 600)]
    by_line = {a.line: a for a in arrivals}
    # Linea e destinazione dal GTFS statico; per corse ignote si usa MATO.
    assert by_line["10"].headsign == "Corso Settembrini" and by_line["10"].trip_id == "T1"
    assert by_line["4"].headsign == "FALCHERA" and by_line["4"].trip_id == "9999U"
    assert by_line["10"].eta_minutes == 5 and by_line["10"].scheduled_ts == FUTURE_TS + 300


def test_parse_filters_by_line(gtfs: GtfsStatic):
    assert [a.line for a in parse_stoptimes(MATO, gtfs, line="10", now=FUTURE_TS)] == ["10"]


def test_parse_unusable_response_is_none(gtfs: GtfsStatic):
    assert parse_stoptimes(b'{"data": {"stop": null}}', gtfs, now=FUTURE_TS) is None
    errors = b'{"errors": [{"message": "boom"}], "data": null}'
    assert parse_stoptimes(errors, gtfs, now=FUTURE_TS) is None


def test_stop_arrivals_prefers_mato(gtfs: GtfsStatic):
    provider = MatoProvider(gtfs)
    arrivals = stop_arrivals(provider, "350", now=FUTURE_TS)
    assert provider.requested == ["0350"]  # palina della fermata, non lo stop_id
    assert [a.line for a in arrivals] == ["55", "10", "4"]


def test_stop_arrivals_falls_back_to_gtt_when_mato_fails(gtfs: GtfsStatic):
    # FakeProvider: MATO irraggiungibile → trip update GTT (55 a +120 s, 10 a +240 s).
    arrivals = stop_arrivals(FakeProvider(gtfs), "350", now=FUTURE_TS)
    assert [(a.line, a.eta_seconds) for a in arrivals] == [("55", 120), ("10", 240)]


def test_stop_arrivals_falls_back_when_stop_unknown_to_mato(gtfs: GtfsStatic):
    provider = MatoProvider(gtfs, payload=b'{"data": {"stop": null}}')
    arrivals = stop_arrivals(provider, "350", now=FUTURE_TS)
    assert [a.line for a in arrivals] == ["55", "10"]

"""Test degli endpoint via TestClient con provider fake (zero rete)."""

from __future__ import annotations

import datetime as dt


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["gtfs_loaded"] is True
    assert body["routes"] == 3 and body["stops"] == 3
    assert isinstance(body["db"], bool)
    assert body["cache"] == "memory"


def test_lines(client):
    r = client.get("/v1/lines")
    assert r.status_code == 200
    lines = r.json()
    assert [line["line"] for line in lines] == ["10", "55"]


def test_stops_search(client):
    r = client.get("/v1/stops/search", params={"q": "massari"})
    assert r.status_code == 200
    res = r.json()
    assert len(res) == 1 and res[0]["stop_id"] == "350"

    # q obbligatorio.
    assert client.get("/v1/stops/search").status_code == 422


def test_arrivals(client):
    r = client.get("/v1/stops/350/arrivals")
    assert r.status_code == 200
    body = r.json()
    assert body["stop_id"] == "350" and body["name"] == "MASSARI CAP."
    assert isinstance(body["lines"], list)
    assert [a["line"] for a in body["arrivals"]] == ["55", "10"]

    r10 = client.get("/v1/stops/350/arrivals", params={"line": "10"})
    arr = r10.json()["arrivals"]
    assert len(arr) == 1 and arr[0]["line"] == "10"


def test_arrivals_unknown_stop_404(client):
    assert client.get("/v1/stops/99999/arrivals").status_code == 404


def test_vehicles(client):
    r = client.get("/v1/lines/10/vehicles")
    assert r.status_code == 200
    body = r.json()
    assert body["line"] == "10" and body["count"] == 2
    assert {v["vehicle_id"] for v in body["vehicles"]} == {"BUS001", "BUS002"}


def test_alerts(client, monkeypatch):
    # Le date delle fixture scioperi sono fisse: congela "oggi" prima di esse.
    monkeypatch.setattr("app.clock.today", lambda: dt.date(2026, 6, 6))
    r = client.get("/v1/alerts")
    assert r.status_code == 200
    body = r.json()
    assert len(body["service_alerts"]) == 2
    # Scioperi filtrati per Torino: Piemonte + nazionale.
    assert len(body["strikes"]) == 2

    r10 = client.get("/v1/alerts", params={"line": "10"})
    body10 = r10.json()
    assert len(body10["service_alerts"]) == 1
    assert body10["service_alerts"][0]["effect"] == "DETOUR"


def test_alerts_keep_strikes_when_gtt_feed_down(client, monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr("app.clock.today", lambda: dt.date(2026, 6, 6))

    def down():
        raise HTTPException(status_code=503)

    monkeypatch.setattr(client.app.state.provider, "alerts_bytes", down)
    body = client.get("/v1/alerts").json()
    assert body["service_alerts_available"] is False
    assert body["service_alerts"] == [] and len(body["strikes"]) == 2

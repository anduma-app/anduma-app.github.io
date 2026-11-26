"""Test CRUD di device/preferiti/sottoscrizioni via TestClient su DB di test.

La sessione DB è sovrascritta su uno SQLite temporaneo: nessuna rete, nessun
DB di sviluppo toccato.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_session
from app.main import app


@pytest.fixture
def client(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'me.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_session():
        s = TestSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _register(client, token="tok-1", platform="android") -> dict[str, str]:
    """Registra un device e restituisce gli header di autenticazione."""
    r = client.post("/v1/me/devices", json={"platform": platform, "token": token})
    assert r.status_code == 201
    body = r.json()
    return {"X-Device-Id": str(body["id"]), "X-Device-Secret": body["secret"]}


# --------------------------------------------------------------------- devices
def test_register_device(client):
    r = client.post("/v1/me/devices", json={"platform": "android", "token": "abc"})
    assert r.status_code == 201
    body = r.json()
    assert body["id"] >= 1 and body["platform"] == "android" and "created_at" in body
    assert len(body["secret"]) >= 32


def test_register_device_idempotent_on_token(client):
    old = _register(client, token="same")
    # Stesso token → stesso device (aggiorna la piattaforma, non duplica).
    r = client.post("/v1/me/devices", json={"platform": "ios", "token": "same"})
    assert r.status_code == 201
    assert str(r.json()["id"]) == old["X-Device-Id"] and r.json()["platform"] == "ios"
    # Il segreto ruota: quello precedente non vale più.
    assert client.get("/v1/me/favorites", headers=old).status_code == 401


def test_register_device_validation(client):
    assert (
        client.post("/v1/me/devices", json={"platform": "windows", "token": "x"}).status_code == 422
    )
    assert client.post("/v1/me/devices", json={"platform": "android"}).status_code == 422


# ------------------------------------------------------------------- auth dep
def test_me_requires_device_credentials(client):
    h = _register(client, token="auth")
    assert client.get("/v1/me/favorites").status_code == 401
    # Il solo id (enumerabile) non basta, né un segreto sbagliato.
    assert (
        client.get("/v1/me/favorites", headers={"X-Device-Id": h["X-Device-Id"]}).status_code == 401
    )
    wrong = {**h, "X-Device-Secret": "x" * 43}
    assert client.get("/v1/me/favorites", headers=wrong).status_code == 401
    assert client.get("/v1/me/favorites", headers=h).status_code == 200


def test_update_device_token_keeps_data(client):
    h = _register(client, token="old-token")
    client.post("/v1/me/favorites", json={"type": "stop", "ref": "350"}, headers=h)
    r = client.put("/v1/me/devices/token", json={"token": "new-token"}, headers=h)
    assert r.status_code == 200
    assert [f["ref"] for f in client.get("/v1/me/favorites", headers=h).json()] == ["350"]
    # Ri-registrarsi col nuovo token ritrova lo stesso device.
    again = client.post("/v1/me/devices", json={"platform": "android", "token": "new-token"})
    assert str(again.json()["id"]) == h["X-Device-Id"]


# --------------------------------------------------------- favorites lifecycle
def test_favorites_crud_and_isolation(client):
    h = _register(client, token="dev-a")
    other = _register(client, token="dev-b")

    assert client.get("/v1/me/favorites", headers=h).json() == []

    r = client.post("/v1/me/favorites", json={"type": "stop", "ref": "350"}, headers=h)
    assert r.status_code == 201
    fav_id = r.json()["id"]
    client.post("/v1/me/favorites", json={"type": "line", "ref": "10"}, headers=h)

    # Idempotente: stesso (type, ref) non duplica.
    again = client.post("/v1/me/favorites", json={"type": "stop", "ref": "350"}, headers=h)
    assert again.json()["id"] == fav_id

    favs = client.get("/v1/me/favorites", headers=h).json()
    assert {(f["type"], f["ref"]) for f in favs} == {("stop", "350"), ("line", "10")}

    # Un altro device non vede i preferiti del primo.
    assert client.get("/v1/me/favorites", headers=other).json() == []

    # Delete proprio → 204; non posso cancellare quello altrui → 404.
    assert client.delete(f"/v1/me/favorites/{fav_id}", headers=h).status_code == 204
    assert client.delete(f"/v1/me/favorites/{fav_id}", headers=other).status_code == 404
    remaining = client.get("/v1/me/favorites", headers=h).json()
    assert {(f["type"], f["ref"]) for f in remaining} == {("line", "10")}


# ----------------------------------------------------- subscriptions lifecycle
def test_subscriptions_crud_and_validation(client):
    h = _register(client, token="dev-sub")

    # imminent ben formata.
    r = client.post(
        "/v1/me/subscriptions",
        json={"kind": "imminent", "stop_id": "350", "line": "10", "threshold_min": 5},
        headers=h,
    )
    assert r.status_code == 201
    sub_id = r.json()["id"]
    assert r.json()["active"] is True

    # strike (solo line).
    assert (
        client.post(
            "/v1/me/subscriptions", json={"kind": "strike", "line": "55"}, headers=h
        ).status_code
        == 201
    )

    # imminent senza i campi richiesti → 422.
    bad = client.post("/v1/me/subscriptions", json={"kind": "imminent", "line": "10"}, headers=h)
    assert bad.status_code == 422
    # strike senza line → 422.
    assert (
        client.post("/v1/me/subscriptions", json={"kind": "strike"}, headers=h).status_code == 422
    )

    subs = client.get("/v1/me/subscriptions", headers=h).json()
    assert {s["kind"] for s in subs} == {"imminent", "strike"}

    # Stessa sottoscrizione → nessun duplicato, soglia aggiornata.
    again = client.post(
        "/v1/me/subscriptions",
        json={"kind": "imminent", "stop_id": "350", "line": "10", "threshold_min": 8},
        headers=h,
    )
    assert again.json()["id"] == sub_id and again.json()["threshold_min"] == 8
    assert len(client.get("/v1/me/subscriptions", headers=h).json()) == 2

    assert client.delete(f"/v1/me/subscriptions/{sub_id}", headers=h).status_code == 204
    assert client.delete("/v1/me/subscriptions/999999", headers=h).status_code == 404
    subs = client.get("/v1/me/subscriptions", headers=h).json()
    assert [s["kind"] for s in subs] == ["strike"]


def test_save_and_reread_roundtrip(client):
    """Criterio 'Fatto': un device salva preferiti e sottoscrizioni e li rilegge."""
    h = _register(client, token="roundtrip")
    client.post("/v1/me/favorites", json={"type": "stop", "ref": "350"}, headers=h)
    client.post(
        "/v1/me/subscriptions",
        json={"kind": "imminent", "stop_id": "350", "line": "10", "threshold_min": 3},
        headers=h,
    )

    favs = client.get("/v1/me/favorites", headers=h).json()
    subs = client.get("/v1/me/subscriptions", headers=h).json()
    assert favs[0]["ref"] == "350"
    assert subs[0]["threshold_min"] == 3


def test_register_web_device(client):
    r = client.post("/v1/me/devices", json={"platform": "web", "token": "tok-web"})
    assert r.status_code in (200, 201)
    assert r.json()["platform"] == "web"


def test_feedback_saved_without_device(client):
    from app.db import Feedback, get_session

    r = client.post(
        "/v1/feedback",
        json={"message": "  Vorrei gli orari  ", "contact": " ", "platform": "web"},
    )
    assert r.status_code == 201
    session = next(app.dependency_overrides[get_session]())
    row = session.query(Feedback).one()
    assert (row.message, row.contact, row.platform) == ("Vorrei gli orari", None, "web")


def test_feedback_rejects_empty_message(client):
    assert client.post("/v1/feedback", json={"message": "    "}).status_code == 422


# ------------------------------------------------------------------ test push
class _FakeSender:
    def __init__(self, exc=None):
        self.sent, self.exc = [], exc

    def send(self, token, message):
        if self.exc:
            raise self.exc
        self.sent.append((token, message.title))


def test_test_push_sends_to_own_device(client, monkeypatch):
    from app.push import PushService

    sender = _FakeSender()
    monkeypatch.setattr("app.me.build_push_service", lambda: PushService(sender))
    h = _register(client, token="tok-test")
    assert client.post("/v1/me/test-push", headers=h).json() == {"sent": True}
    assert sender.sent == [("tok-test", "Notifica di prova")]


def test_test_push_reports_errors(client, monkeypatch):
    from app.push import InvalidTokenError, PushService

    h = _register(client, token="tok-err")
    monkeypatch.setattr("app.me.build_push_service", lambda: None)
    assert client.post("/v1/me/test-push", headers=h).status_code == 503
    bad = PushService(_FakeSender(InvalidTokenError("tok-err")))
    monkeypatch.setattr("app.me.build_push_service", lambda: bad)
    assert client.post("/v1/me/test-push", headers=h).status_code == 410
    boom = PushService(_FakeSender(RuntimeError("quota")))
    monkeypatch.setattr("app.me.build_push_service", lambda: boom)
    r = client.post("/v1/me/test-push", headers=h)
    assert r.status_code == 502 and "quota" in r.json()["detail"]

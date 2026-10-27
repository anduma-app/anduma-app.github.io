"""Endpoint utente (v1): device anonimo, preferiti, sottoscrizioni.

Identità MVP: il client registra un device via ``POST /v1/me/devices`` e riceve
un segreto casuale; nelle altre chiamate ``/me/*`` si identifica con gli header
``X-Device-Id`` + ``X-Device-Secret``. Nel DB c'è solo l'hash del segreto. Nessun
account: l'autenticazione vera arriverà dopo (vedi SPEC §4).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import Device, Favorite, Subscription, get_session
from .models import (
    DeviceCreate,
    DeviceOut,
    DeviceRegistered,
    DeviceTokenUpdate,
    FavoriteCreate,
    FavoriteOut,
    SubscriptionCreate,
    SubscriptionOut,
)

router = APIRouter(prefix="/me", tags=["me"])


def _hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def get_current_device(
    x_device_id: int | None = Header(None, alias="X-Device-Id"),
    x_device_secret: str | None = Header(None, alias="X-Device-Secret"),
    session: Session = Depends(get_session),
) -> Device:
    """Risolve il device dagli header ``X-Device-Id`` + ``X-Device-Secret`` (401 se non validi)."""
    if x_device_id is None or not x_device_secret:
        raise HTTPException(status_code=401, detail="Credenziali device mancanti")
    device = session.get(Device, x_device_id)
    if (
        device is None
        or device.secret_hash is None
        or not hmac.compare_digest(device.secret_hash, _hash_secret(x_device_secret))
    ):
        raise HTTPException(status_code=401, detail="Device non autenticato")
    return device


# --------------------------------------------------------------------- devices
@router.post("/devices", response_model=DeviceRegistered, status_code=201)
def register_device(
    body: DeviceCreate, session: Session = Depends(get_session)
) -> DeviceRegistered:
    """Registra (o ri-registra) un device anonimo. Idempotente sul token FCM.

    Ogni registrazione genera un nuovo segreto: solo chi possiede il token FCM
    (cioè l'app installata) può ottenerlo.
    """
    secret = secrets.token_urlsafe(32)
    for _attempt in range(2):
        device = session.scalar(select(Device).where(Device.fcm_token == body.token))
        if device is None:
            device = Device(fcm_token=body.token)
            session.add(device)
        device.platform = body.platform
        device.secret_hash = _hash_secret(secret)
        try:
            session.commit()
            break
        except IntegrityError:
            # Registrazione concorrente con lo stesso token: riprova sull'esistente.
            session.rollback()
    else:
        raise HTTPException(status_code=409, detail="Registrazione concorrente, riprovare")
    session.refresh(device)
    return DeviceRegistered(**DeviceOut.model_validate(device).model_dump(), secret=secret)


@router.put("/devices/token", response_model=DeviceOut)
def update_device_token(
    body: DeviceTokenUpdate,
    device: Device = Depends(get_current_device),
    session: Session = Depends(get_session),
) -> DeviceOut:
    """Aggiorna il token FCM ruotato, mantenendo preferiti e sottoscrizioni."""
    other = session.scalar(
        select(Device).where(Device.fcm_token == body.token, Device.id != device.id)
    )
    if other is not None:
        # Il token appartiene a questa installazione: il vecchio record è orfano.
        session.delete(other)
        session.flush()
    device.fcm_token = body.token
    session.commit()
    return DeviceOut.model_validate(device)


# ------------------------------------------------------------------- favorites
@router.get("/favorites", response_model=list[FavoriteOut])
def list_favorites(
    device: Device = Depends(get_current_device),
    session: Session = Depends(get_session),
) -> list[FavoriteOut]:
    rows = session.scalars(
        select(Favorite).where(Favorite.device_id == device.id).order_by(Favorite.id)
    ).all()
    return [FavoriteOut.model_validate(r) for r in rows]


@router.post("/favorites", response_model=FavoriteOut, status_code=201)
def add_favorite(
    body: FavoriteCreate,
    device: Device = Depends(get_current_device),
    session: Session = Depends(get_session),
) -> FavoriteOut:
    # Idempotente: stesso (device, type, ref) → ritorna l'esistente.
    existing = session.scalar(
        select(Favorite).where(
            Favorite.device_id == device.id,
            Favorite.type == body.type,
            Favorite.ref == body.ref,
        )
    )
    if existing is not None:
        return FavoriteOut.model_validate(existing)
    fav = Favorite(device_id=device.id, type=body.type, ref=body.ref)
    session.add(fav)
    session.commit()
    session.refresh(fav)
    return FavoriteOut.model_validate(fav)


@router.delete("/favorites/{favorite_id}", status_code=204)
def delete_favorite(
    favorite_id: int,
    device: Device = Depends(get_current_device),
    session: Session = Depends(get_session),
) -> None:
    fav = session.get(Favorite, favorite_id)
    if fav is None or fav.device_id != device.id:
        raise HTTPException(status_code=404, detail="Preferito non trovato")
    session.delete(fav)
    session.commit()


# --------------------------------------------------------------- subscriptions
@router.get("/subscriptions", response_model=list[SubscriptionOut])
def list_subscriptions(
    device: Device = Depends(get_current_device),
    session: Session = Depends(get_session),
) -> list[SubscriptionOut]:
    rows = session.scalars(
        select(Subscription).where(Subscription.device_id == device.id).order_by(Subscription.id)
    ).all()
    return [SubscriptionOut.model_validate(r) for r in rows]


@router.post("/subscriptions", response_model=SubscriptionOut, status_code=201)
def add_subscription(
    body: SubscriptionCreate,
    device: Device = Depends(get_current_device),
    session: Session = Depends(get_session),
) -> SubscriptionOut:
    # Idempotente su (device, kind, fermata, linea): aggiorna la soglia dell'esistente.
    sub = session.scalar(
        select(Subscription).where(
            Subscription.device_id == device.id,
            Subscription.kind == body.kind,
            Subscription.stop_id.is_(None)
            if body.stop_id is None
            else Subscription.stop_id == body.stop_id,
            Subscription.line.is_(None) if body.line is None else Subscription.line == body.line,
        )
    )
    if sub is None:
        sub = Subscription(
            device_id=device.id, kind=body.kind, stop_id=body.stop_id, line=body.line
        )
        session.add(sub)
    sub.threshold_min = body.threshold_min
    sub.active = True
    session.commit()
    session.refresh(sub)
    return SubscriptionOut.model_validate(sub)


@router.delete("/subscriptions/{subscription_id}", status_code=204)
def delete_subscription(
    subscription_id: int,
    device: Device = Depends(get_current_device),
    session: Session = Depends(get_session),
) -> None:
    sub = session.get(Subscription, subscription_id)
    if sub is None or sub.device_id != device.id:
        raise HTTPException(status_code=404, detail="Sottoscrizione non trovata")
    session.delete(sub)
    session.commit()


__all__ = ["router", "get_current_device"]

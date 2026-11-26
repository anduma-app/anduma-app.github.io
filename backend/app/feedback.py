"""Feedback dall'app (segnalazioni e richieste di funzionalità).

Prima si salva nella tabella ``feedback``, poi, dopo aver risposto al client, si
apre una issue sul repo GitHub (se ``TT_GITHUB_TOKEN`` è impostato). Un errore di
GitHub non arriva all'utente: finisce solo nei log, il feedback resta salvato.
Il recapito (``contact``) non va mai nella issue: il repo è pubblico.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import threading
import time
from collections import deque

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .clock import ROME
from .config import Settings, get_settings
from .db import Feedback, get_session
from .models import FeedbackCreate

log = logging.getLogger(__name__)
router = APIRouter(tags=["feedback"])

_TITLE_MAX_WORDS = 8
_TITLE_MAX_CHARS = 70


class RateLimiter:
    """Finestra scorrevole di 60 s per chiave (IP). In memoria: una sola istanza."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            # Pulizia delle chiavi scadute: la mappa non cresce senza limite.
            for k in [k for k, q in self._hits.items() if q and q[-1] <= now - 60]:
                del self._hits[k]
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - 60:
                hits.popleft()
            if len(hits) >= limit:
                return False
            hits.append(now)
            return True

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def rate_limit(request: Request, settings: Settings = Depends(get_settings)) -> None:
    """Conta ogni invio (anche non valido) per IP; oltre la soglia risponde 429."""
    ip = (settings.client_ip_header and request.headers.get(settings.client_ip_header)) or (
        request.client.host if request.client else "unknown"
    )
    if not limiter.allow(ip, settings.feedback_max_per_minute):
        raise HTTPException(status_code=429, detail="Troppi invii: riprova tra un minuto")


def issue_title(message: str) -> str:
    """Le prime parole del messaggio, su una riga."""
    words = message.split()
    title = " ".join(words[:_TITLE_MAX_WORDS])
    if len(title) > _TITLE_MAX_CHARS:
        title = title[:_TITLE_MAX_CHARS].rsplit(" ", 1)[0] or title[:_TITLE_MAX_CHARS]
    return title + ("…" if title != " ".join(words) else "")


def issue_body(message: str, platform: str | None, created_at: dt.datetime) -> str:
    """Messaggio in un blocco di codice: niente @menzioni né markdown dell'utente."""
    longest = max((len(m) for m in re.findall(r"`+", message)), default=0)
    fence = "`" * max(3, longest + 1)
    when = created_at.astimezone(ROME).strftime("%d/%m/%Y %H:%M")
    return (
        f"{fence}text\n{message}\n{fence}\n\n"
        f"- **Piattaforma:** {platform or 'non indicata'}\n"
        f"- **Data:** {when} (ora di Roma)\n\n"
        "_Issue creata automaticamente dal modulo di feedback dell'app._\n"
    )


def open_issue(settings: Settings, title: str, body: str) -> None:
    """Crea la issue su GitHub. Non solleva mai: gli errori vanno nei log."""
    url = f"https://api.github.com/repos/{settings.github_repo}/issues"
    try:
        res = httpx.post(
            url,
            json={"title": title, "body": body, "labels": ["feedback"]},
            headers={
                "Authorization": f"Bearer {settings.github_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "transito-torino-backend",
            },
            timeout=10,
        )
    except httpx.HTTPError as exc:
        log.warning("Issue GitHub per il feedback non creata: %s", exc)
        return
    if res.status_code >= 300:
        log.warning(
            "Issue GitHub per il feedback non creata: HTTP %s %s",
            res.status_code,
            res.text[:300],
        )
        return
    log.info("Feedback pubblicato come issue: %s", res.json().get("html_url"))


@router.post("/feedback", status_code=201, dependencies=[Depends(rate_limit)])
def create_feedback(
    body: FeedbackCreate,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    contact = (body.contact or "").strip() or None
    row = Feedback(message=body.message, contact=contact, platform=body.platform)
    session.add(row)
    session.commit()
    if settings.github_token:
        created_at = row.created_at or dt.datetime.now(dt.UTC)
        background.add_task(
            open_issue,
            settings,
            issue_title(body.message),
            issue_body(body.message, body.platform, created_at),
        )
    return {"ok": True}

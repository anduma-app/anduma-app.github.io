"""Feedback dall'app (segnalazioni e richieste di funzionalità), salvato nel DB.

Anonimo: non richiede un device registrato. Si legge dalla tabella ``feedback``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .db import Feedback, get_session
from .models import FeedbackCreate

router = APIRouter(tags=["feedback"])


@router.post("/feedback", status_code=201)
def create_feedback(body: FeedbackCreate, session: Session = Depends(get_session)) -> dict:
    contact = (body.contact or "").strip() or None
    session.add(Feedback(message=body.message, contact=contact, platform=body.platform))
    session.commit()
    return {"ok": True}

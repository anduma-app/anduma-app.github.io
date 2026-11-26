"""Scioperi dei trasporti (MIT): parser difensivo del feed RSS + filtro per GTT.

Il feed RSS dell'Osservatorio sui Conflitti Sindacali elenca gli scioperi in
programma; ogni ``<item>`` porta i campi come righe ``Chiave: valore`` nella
descrizione. Le chiavi si riconoscono in modo case-insensitive su più alias,
perché il formato può cambiare nel tempo. (Il vecchio CSV su dati.mit.gov.it
è fermo al 2020 e non va usato.)

Per Torino si tengono gli scioperi del trasporto pubblico locale e quelli
generali/plurisettoriali, se nazionali su tutta Italia o in Piemonte/Torino; in
Piemonte anche il ferroviario (GTT gestisce la ferrovia Torino-Ceres).
"""

from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET

import httpx

from . import clock
from .config import Settings, get_settings
from .models import Strike

# Alias (lowercase, match per prefisso) delle chiavi nel testo di ogni item.
_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "start_date": ("data inizio",),
    "end_date": ("data fine",),
    "sector": ("settore",),
    "relevance": ("rilevanza",),
    "region": ("regione",),
    "province": ("provincia",),
    "unions": ("sindacat",),
    "category": ("categoria",),
}

_LOCAL_PLACES = ("piemonte", "torino")
_TPL_SECTORS = ("pubblico locale", "generale", "plurisettoriale")


def _fields(text: str, sep: str = "<br/>") -> dict[str, str]:
    """Coppie ``Chiave: valore`` separate da ``sep`` (`` - `` nel titolo)."""
    out: dict[str, str] = {}
    for part in text.replace("<br />", "<br/>").split(sep):
        key, sep, value = part.partition(":")
        if sep and key.strip():
            out.setdefault(key.strip(), value.strip())
    return out


def _pick(fields: dict[str, str], field: str) -> str | None:
    for key, value in fields.items():
        low = key.lower()
        if any(low.startswith(alias) for alias in _FIELD_ALIASES[field]):
            return value or None
    return None


def parse_strikes_rss(text: str) -> list[Strike]:
    """Parsa il feed RSS MIT; feed vuoto o malformato → lista vuota."""
    try:
        root = ET.fromstring(text.lstrip("\ufeff").strip())
    except ET.ParseError:
        return []
    out: list[Strike] = []
    for item in root.iter("item"):
        fields = _fields(item.findtext("title") or "", sep=" - ")
        fields.update(_fields(item.findtext("description") or ""))
        guid = (item.findtext("guid") or "").strip()
        if guid:
            fields["guid"] = guid
        region = _pick(fields, "region")
        province = _pick(fields, "province")
        specific = province and province.lower() not in ("tutte", "tutti")
        out.append(
            Strike(
                start_date=_pick(fields, "start_date"),
                end_date=_pick(fields, "end_date"),
                sector=_pick(fields, "sector"),
                relevance=_pick(fields, "relevance"),
                area=province if specific else region,
                unions=_pick(fields, "unions"),
                category=_pick(fields, "category"),
                raw=fields,
            )
        )
    return out


def is_relevant_for_torino(strike: Strike) -> bool:
    """True se lo sciopero può fermare il servizio GTT."""
    sector = (strike.sector or "").lower()
    relevance = (strike.relevance or "").lower()
    place = " ".join(
        [strike.area or "", strike.raw.get("Regione", ""), strike.raw.get("Provincia", "")]
    ).lower()
    tpl_like = any(s in sector for s in _TPL_SECTORS)
    if any(p in place for p in _LOCAL_PLACES):
        return tpl_like or "ferroviario" in sector
    # Nazionali solo se registrati su tutta Italia: il MIT associa a volte uno
    # sciopero "nazionale" a un'altra regione (es. Toscana), che non riguarda GTT.
    region = (strike.raw.get("Regione") or strike.area or "").strip().lower()
    return tpl_like and relevance == "nazionale" and region in ("", "italia")


def filter_for_torino(strikes: list[Strike]) -> list[Strike]:
    return [s for s in strikes if is_relevant_for_torino(s)]


_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y")


def parse_date(value: str | None) -> dt.date | None:
    """Parsa una data in vari formati comuni; None se non riconoscibile."""
    if not value:
        return None
    s = value.strip()[:10]
    for fmt in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


# Quanto indietro/avanti consideriamo uno sciopero "rilevante" (giorni).
_GRACE_DAYS = 2  # tolleranza per scioperi iniziati da poco / errori di fuso
# Gli scioperi sono indetti al più ~un anno prima: oltre i ~13 mesi è quasi
# certamente un refuso sulla data (es. fine "2107" per "2017").
_HORIZON_DAYS = 400


def is_active_strike(strike: Strike, today: dt.date | None = None) -> bool:
    """True se lo sciopero è in corso o imminente, entro una finestra plausibile.

    Il feed elenca gli scioperi in programma, ma i dati MIT hanno storicamente
    refusi sulle date (es. fine ``2107`` per ``2017``). Affidarsi alla sola *fine*
    lascia passare questi casi. Qui uno sciopero è rilevante se **inizio o fine** cadono
    nella finestra ``[oggi - grace, oggi + orizzonte]``: scarta sia il passato sia
    le date assurdamente future. Se nessuna data è parsabile, NON scartiamo
    (difensivo: meglio mostrarne uno in più che nascondere uno sciopero reale).
    """
    today = today or clock.today()
    lo = today - dt.timedelta(days=_GRACE_DAYS)
    hi = today + dt.timedelta(days=_HORIZON_DAYS)
    start = parse_date(strike.start_date)
    end = parse_date(strike.end_date)
    if start is None and end is None:
        return True
    # Sciopero ancora in corso: iniziato nel passato ma con fine plausibile ≥ oggi.
    if end is not None and today <= end <= hi:
        return True
    # Inizio (o fine, se l'inizio manca) entro la finestra.
    ref = start or end
    return ref is not None and lo <= ref <= hi


def filter_upcoming(strikes: list[Strike], today: dt.date | None = None) -> list[Strike]:
    """Tiene solo gli scioperi in corso o futuri."""
    return [s for s in strikes if is_active_strike(s, today)]


def download_strikes_rss(settings: Settings | None = None) -> str:
    """Scarica il feed RSS scioperi (rete). Isolato per testabilità."""
    settings = settings or get_settings()
    resp = httpx.get(
        settings.strikes_rss_url,
        timeout=settings.http_timeout,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (compatible; Anduma/1.0)"},
    )
    resp.raise_for_status()
    return resp.text


__all__ = [
    "parse_strikes_rss",
    "is_relevant_for_torino",
    "filter_for_torino",
    "is_active_strike",
    "parse_date",
    "filter_upcoming",
    "download_strikes_rss",
]

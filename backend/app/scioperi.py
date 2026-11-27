"""Scioperi dei trasporti: calendario CGSSE (fonte in uso) o feed RSS MIT + filtro per GTT.

Fonte in uso: il calendario della Commissione di Garanzia Sciopero (cgsse.it),
letto dall'elenco HTML. Il feed RSS del MIT (Osservatorio sui Conflitti Sindacali)
ha gli stessi dati, ma il sito non risponde ai server in datacenter (Render, GitHub
Actions): il parser resta per le fixture e per chi ospita il backend in Italia.
Il downloader salva gli scioperi già normalizzati in JSON; ``parse_strikes`` legge
sia quello sia l'RSS. (Il vecchio CSV su dati.mit.gov.it è fermo al 2020.)

Per Torino si tengono gli scioperi del trasporto pubblico locale e quelli
generali/plurisettoriali, se nazionali su tutta Italia o in Piemonte/Torino; in
Piemonte anche il ferroviario (GTT gestisce la ferrovia Torino-Ceres).
"""

from __future__ import annotations

import datetime as dt
import html
import json
import re
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


# ------------------------------------------------------------------------ CGSSE
_CGSSE_FIELD = re.compile(r'label-sciopero">\s*([^<]+?)\s*</div>(.*?)</div>', re.S)
_CGSSE_ID = re.compile(r"/calendario-scioperi/dettaglio-sciopero/(\d+)")
_CGSSE_DATE = re.compile(r"(\d{2})-(\d{2})-(\d{4})")
_CGSSE_PAGE_SIZE = 15  # righe per pagina dell'elenco
_CGSSE_MAX_PAGES = 5  # tetto per un singolo giorno con molte righe
_CGSSE_DAYS = 120  # quanto avanti leggere il calendario
# Settori che possono fermare GTT (id della tassonomia del sito): TPL (anche gli
# scioperi multisettore che lo includono), ferroviario, generali e plurisettoriali
# nazionali/regionali/provinciali. Gli altri non servono e allungherebbero l'elenco.
_CGSSE_SECTORS = ("112", "110", "382", "384", "386", "376", "378")


def _text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def cgsse_ids(page: str) -> list[str]:
    """Id degli scioperi in una pagina dell'elenco, in ordine e senza ripetizioni."""
    return list(dict.fromkeys(_CGSSE_ID.findall(page)))


def parse_cgsse(listing: str, revoked_ids: set[str] | frozenset[str] = frozenset()) -> list[Strike]:
    """Scioperi dall'elenco HTML del calendario CGSSE (anche più pagine concatenate).

    Ogni riga ha Data, Settore, Azienda, Sindacato, Ambito geografico, Modalità e il
    link al dettaglio (il cui id fa da ``guid``). L'elenco include anche gli scioperi
    revocati, senza segnarli: si escludono con ``revoked_ids`` (elenco con il filtro
    ``revocato=1``). Ambito vuoto = sciopero nazionale.
    """
    rows: list[dict[str, str]] = []
    for key, value in _CGSSE_FIELD.findall(listing):
        if key == "Data":
            rows.append({})
        if not rows:
            continue
        if key == "Dettagli":
            ids = _CGSSE_ID.findall(value)
            if ids:
                rows[-1]["id"] = ids[0]
        else:
            rows[-1][key] = _text(value)
    out: list[Strike] = []
    seen: set[str] = set()
    for row in rows:
        sid = row.get("id")
        if not sid or sid in seen or sid in revoked_ids:
            continue
        seen.add(sid)
        dates = ["/".join(d) for d in _CGSSE_DATE.findall(row.get("Data", ""))]
        area = row.get("Ambito geografico") or None
        raw = {k: v for k, v in row.items() if k != "id"}
        raw["guid"] = f"https://cgsse.it/calendario-scioperi/dettaglio-sciopero/{sid}"
        out.append(
            Strike(
                start_date=dates[0] if dates else None,
                end_date=dates[-1] if dates else None,
                sector=row.get("Settore") or None,
                relevance="Locale" if area else "Nazionale",
                area=area,
                unions=row.get("Sindacato") or None,
                category=row.get("Azienda") or None,
                raw=raw,
            )
        )
    return out


def _cgsse_window(
    client: httpx.Client, url: str, params: dict, start: dt.date, end: dt.date
) -> list[str]:
    """Pagine dell'elenco per le date ``start``–``end`` (incluse), senza paginare.

    La paginazione del sito non è affidabile (righe con la stessa data finiscono su
    più pagine o su nessuna). Una pagina non piena è completa; una piena si divide a
    metà finché ogni finestra ci sta. Un solo giorno ancora pieno: si leggono le
    pagine successive (caso raro, al meglio).
    """
    query = {**params, "data_inizio": start.isoformat(), "data_fine": end.isoformat()}
    resp = client.get(url, params=query)
    resp.raise_for_status()
    if len(cgsse_ids(resp.text)) < _CGSSE_PAGE_SIZE:
        return [resp.text]
    if start < end:
        mid = start + (end - start) // 2
        return _cgsse_window(client, url, params, start, mid) + _cgsse_window(
            client, url, params, mid + dt.timedelta(days=1), end
        )
    pages = [resp.text]
    for n in range(1, _CGSSE_MAX_PAGES):
        resp = client.get(url, params={**query, "page": str(n)})
        resp.raise_for_status()
        pages.append(resp.text)
        if len(cgsse_ids(resp.text)) < _CGSSE_PAGE_SIZE:
            break
    return pages


def download_strikes(settings: Settings | None = None) -> str:
    """Scarica il calendario CGSSE dei prossimi mesi (rete): JSON degli scioperi."""
    settings = settings or get_settings()
    today = clock.today()
    start = today - dt.timedelta(days=_GRACE_DAYS)
    end = today + dt.timedelta(days=_CGSSE_DAYS)
    params = {"settore[]": list(_CGSSE_SECTORS)}
    with httpx.Client(
        timeout=settings.http_timeout,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (compatible; Anduma/1.0)"},
    ) as client:
        listing = "".join(_cgsse_window(client, settings.strikes_url, params, start, end))
        revoked_pages = _cgsse_window(
            client, settings.strikes_url, {**params, "revocato": "1"}, start, end
        )
    revoked = {sid for page in revoked_pages for sid in cgsse_ids(page)}
    if 'name="data_inizio"' not in listing:  # non è la pagina del calendario
        raise ValueError("Calendario CGSSE non riconosciuto: formato cambiato?")
    strikes = sorted(
        parse_cgsse(listing, revoked), key=lambda x: parse_date(x.start_date) or dt.date.max
    )
    return json.dumps([s.model_dump() for s in strikes], ensure_ascii=False)


def parse_strikes(text: str) -> list[Strike]:
    """Scioperi dal contenuto scaricato: JSON (CGSSE) o feed RSS MIT."""
    stripped = text.lstrip("\ufeff").strip()
    if stripped.startswith("["):
        try:
            return [Strike(**item) for item in json.loads(stripped)]
        except (ValueError, TypeError):
            return []
    return parse_strikes_rss(stripped)


__all__ = [
    "download_strikes",
    "parse_cgsse",
    "parse_strikes",
    "parse_strikes_rss",
    "is_relevant_for_torino",
    "filter_for_torino",
    "is_active_strike",
    "parse_date",
    "filter_upcoming",
]

"""Test dei parser scioperi (calendario CGSSE, feed RSS MIT) e del filtro per Torino."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import httpx

from app.models import Strike
from app.scioperi import (
    _cgsse_window,
    cgsse_ids,
    filter_for_torino,
    filter_upcoming,
    is_active_strike,
    is_relevant_for_torino,
    parse_cgsse,
    parse_strikes,
    parse_strikes_rss,
)

CGSSE = (Path(__file__).parent / "fixtures" / "cgsse_elenco.html").read_text(encoding="utf-8")


def test_filter_upcoming_drops_past_strikes():
    today = dt.date(2026, 6, 6)
    strikes = [
        Strike(start_date="2014-01-08", end_date="2014-01-08"),  # passato
        Strike(start_date="2026-06-10", end_date="2026-06-10"),  # futuro
        Strike(start_date="2026-06-06", end_date="2026-06-06"),  # oggi
        Strike(start_date="data ignota", end_date=None),  # non parsabile → tenuto
    ]
    kept = filter_upcoming(strikes, today=today)
    assert len(kept) == 3
    assert all(s.start_date != "2014-01-08" for s in kept)


def test_is_active_strike_date_formats():
    today = dt.date(2026, 6, 6)
    assert is_active_strike(Strike(start_date="10/06/2026"), today)  # DD/MM/YYYY
    assert not is_active_strike(Strike(start_date="01/01/2020"), today)
    assert is_active_strike(Strike(start_date=None), today)  # difensivo


def test_is_active_strike_rejects_typo_future_end():
    """Refuso nel dato MIT: inizio 2017, fine '2107' (per 2017). Va scartato."""
    today = dt.date(2026, 6, 6)
    assert not is_active_strike(Strike(start_date="2017-07-06", end_date="2107-07-06"), today)
    # Anche una fine assurdamente futura da sola non basta a tenerlo.
    assert not is_active_strike(Strike(start_date=None, end_date="2107-07-06"), today)


def test_is_active_strike_keeps_ongoing_multiday():
    """Sciopero iniziato qualche giorno fa ma con fine ancora futura: tenuto."""
    today = dt.date(2026, 6, 6)
    assert is_active_strike(Strike(start_date="2026-06-01", end_date="2026-06-08"), today)


def test_parse_rss_items(strikes_feed: str):
    strikes = parse_strikes_rss(strikes_feed)
    assert len(strikes) == 4
    first = strikes[0]
    assert first.start_date == "10/06/2026" and first.end_date == "10/06/2026"
    assert first.sector == "Trasporto pubblico locale"
    assert first.area == "Torino"  # provincia specifica
    assert first.unions == "FILT-CGIL"
    assert first.raw["guid"] == "http://scioperi.mit.gov.it/9001"
    # Il separatore " - " vale solo nel titolo: la modalità resta intera.
    assert first.raw["modalità"].endswith("SECONDA FASCIA")
    assert strikes[1].area == "Italia"  # provincia "Tutte" → regione


def test_filter_keeps_torino_tpl_and_national_general(strikes_feed: str):
    kept = filter_for_torino(parse_strikes_rss(strikes_feed))
    assert [(s.sector, s.area) for s in kept] == [
        ("Trasporto pubblico locale", "Torino"),
        ("Generale", "Italia"),
    ]


def test_relevance_rules():
    assert is_relevant_for_torino(Strike(sector="Trasporto pubblico locale", area="Piemonte"))
    assert is_relevant_for_torino(Strike(sector="Ferroviario", area="Torino"))  # Torino-Ceres
    assert is_relevant_for_torino(Strike(sector="Plurisettoriale", relevance="Nazionale"))
    assert is_relevant_for_torino(
        Strike(sector="Generale", relevance="Nazionale", area="Italia", raw={"Regione": " Italia"})
    )
    # "Nazionale" ma registrato su un'altra regione: escluso.
    assert not is_relevant_for_torino(
        Strike(
            sector="Plurisettoriale",
            relevance="Nazionale",
            area="Toscana",
            raw={"Regione": "Toscana"},
        )
    )
    assert not is_relevant_for_torino(Strike(sector="Aereo", relevance="Nazionale"))
    assert not is_relevant_for_torino(Strike(sector="Ferroviario", relevance="Nazionale"))
    assert not is_relevant_for_torino(
        Strike(sector="Trasporto pubblico locale", relevance="Locale", area="Sicilia")
    )


def test_malformed_or_empty_feed_is_safe():
    assert parse_strikes_rss("") == []
    assert parse_strikes_rss("<rss><channel>") == []
    assert parse_strikes_rss("<rss><channel></channel></rss>") == []


# ------------------------------------------------------------------------ CGSSE
def test_parse_cgsse_rows():
    strikes = {s.raw["guid"].rsplit("/", 1)[1]: s for s in parse_cgsse(CGSSE)}
    assert len(strikes) == 7
    multi = strikes["1002"]
    assert (multi.start_date, multi.end_date) == ("12/02/2027", "13/02/2027")
    assert multi.sector == "Trasporto ferroviario" and multi.area == "PIEMONTE"
    assert multi.relevance == "Locale" and multi.unions == "Filt Cgil" and multi.category == "GTT"
    assert multi.raw["guid"] == "https://cgsse.it/calendario-scioperi/dettaglio-sciopero/1002"
    national = strikes["1001"]
    assert national.area is None and national.relevance == "Nazionale"
    assert national.start_date == national.end_date == "02/02/2027"
    assert strikes["1004"].raw["Modalità"] == "intera giornata & fasce di garanzia"


def test_parse_cgsse_drops_revoked_and_repeated_rows():
    twice = CGSSE + CGSSE  # il sito ripete l'ultima pagina
    ids = [s.raw["guid"].rsplit("/", 1)[1] for s in parse_cgsse(twice, {"1005"})]
    assert ids == ["1001", "1002", "1003", "1004", "1006", "1007"]
    assert parse_cgsse("<html>formato cambiato</html>") == []


def test_cgsse_relevance_for_torino():
    kept = filter_for_torino(parse_cgsse(CGSSE, {"1005"}))
    ids = sorted(s.raw["guid"].rsplit("/", 1)[1] for s in kept)
    # TPL nazionale, ferroviario in Piemonte, TPL a Torino, generale nazionale.
    # Esclusi: TPL a Napoli, aereo, il revocato.
    assert ids == ["1001", "1002", "1004", "1007"]


def test_parse_strikes_reads_json_and_rss(strikes_feed):
    strikes = parse_cgsse(CGSSE)
    as_json = json.dumps([s.model_dump() for s in strikes], ensure_ascii=False)
    assert parse_strikes(as_json) == strikes
    assert parse_strikes(strikes_feed) == parse_strikes_rss(strikes_feed)
    assert parse_strikes("[rotto") == []
    assert parse_strikes("") == []


def test_cgsse_window_splits_full_pages_instead_of_paginating():
    full = "".join(
        CGSSE.replace("dettaglio-sciopero/100", f"dettaglio-sciopero/{k}0") for k in (1, 2, 3)
    )
    assert len(cgsse_ids(full)) == 21  # oltre le 15 righe di una pagina
    seen = []

    def handler(request):
        start, end = request.url.params["data_inizio"], request.url.params["data_fine"]
        seen.append((start, end, request.url.params.get("page")))
        # Più di 10 giorni: pagina piena (il resto andrebbe a pagina 2, inaffidabile).
        span = (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days
        return httpx.Response(200, text=full if span > 10 else CGSSE)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    pages = _cgsse_window(
        client,
        "https://cgsse.it/calendario-scioperi",
        {},
        dt.date(2026, 12, 1),
        dt.date(2026, 12, 31),
    )
    assert [s[:2] for s in seen] == [
        ("2026-12-01", "2026-12-31"),
        ("2026-12-01", "2026-12-16"),
        ("2026-12-01", "2026-12-08"),
        ("2026-12-09", "2026-12-16"),
        ("2026-12-17", "2026-12-31"),
        ("2026-12-17", "2026-12-24"),
        ("2026-12-25", "2026-12-31"),
    ]
    assert all(page is None for *_, page in seen)  # mai la paginazione del sito
    assert len(pages) == 4

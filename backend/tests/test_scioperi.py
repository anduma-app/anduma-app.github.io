"""Test del parser difensivo del feed scioperi MIT e del filtro per Torino."""

from __future__ import annotations

import datetime as dt

from app.models import Strike
from app.scioperi import (
    filter_for_torino,
    filter_upcoming,
    is_active_strike,
    is_relevant_for_torino,
    parse_strikes_rss,
)


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

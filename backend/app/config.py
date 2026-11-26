"""Configurazione centralizzata: URL dei feed, TTL della cache, settings.

Tutti gli URL stanno qui (non sparsi nel codice): il link di download del GTFS
statico e gli endpoint GTT/MIT possono cambiare nel tempo. Override via variabili
d'ambiente con prefisso ``TT_`` o file ``.env`` (vedi pydantic-settings).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings dell'applicazione, sovrascrivibili da env (prefisso ``TT_``)."""

    model_config = SettingsConfigDict(
        env_prefix="TT_", env_file=".env", extra="ignore", populate_by_name=True
    )

    # --- GTFS statico (orari, fermate, percorsi) ---
    # Trappola nota: il link diretto di download dello ZIP può cambiare (404).
    # Se cambia, aggiornare QUI (o via env TT_GTFS_STATIC_URL), non nel codice.
    # Link diretto allo ZIP (verificato). Pagina del dataset:
    # https://aperto.comune.torino.it/dataset/feed-gtfs-trasporti-gtt
    gtfs_static_url: str = "https://www.gtt.to.it/open_data/gtt_gtfs.zip"

    # --- GTFS-Realtime (protobuf binario, NON JSON) ---
    rt_vehicle_positions_url: str = (
        "https://percorsieorari.gtt.to.it/das_gtfsrt/vehicle_position.aspx"
    )
    rt_trip_updates_url: str = "https://percorsieorari.gtt.to.it/das_gtfsrt/trip_update.aspx"
    rt_alerts_url: str = "https://percorsieorari.gtt.to.it/das_gtfsrt/alerts.aspx"

    # --- Scioperi (MIT, Osservatorio sui Conflitti Sindacali) ---
    # Feed RSS degli scioperi in programma. Il CSV su dati.mit.gov.it è fermo al 2020.
    strikes_rss_url: str = "https://scioperi.mit.gov.it/mit2/public/scioperi/rss"

    # --- TTL cache (secondi) ---
    ttl_vehicle_positions: int = 12
    ttl_trip_updates: int = 12
    ttl_alerts: int = 60
    ttl_strikes: int = 3600
    ttl_gtfs_static: int = 24 * 3600

    # --- HTTP ---
    http_timeout: float = 15.0
    # Attesa prima di ritentare un download GTFS/scioperi fallito (si serve lo snapshot precedente).
    retry_backoff_s: int = 300

    # --- Persistenza ---
    # SQLite per iniziare; in produzione PostgreSQL via env, es.
    #   TT_DATABASE_URL=postgresql+psycopg://user:pass@host:5432/transito
    database_url: str = "sqlite:///./transito.db"
    db_echo: bool = False

    @field_validator("database_url")
    @classmethod
    def _use_psycopg_driver(cls, value: str) -> str:
        """Accetta le stringhe dei provider (``postgres://``, ``postgresql://``) così come sono.

        SQLAlchemy userebbe psycopg2 (non installato): si forza il driver psycopg 3.
        """
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                return "postgresql+psycopg://" + value.removeprefix(prefix)
        return value

    # --- Cache ---
    # Vuoto → cache in-memory (sviluppo). In produzione: redis://host:6379/0
    redis_url: str = ""

    # --- Logging ---
    log_level: str = "info"

    # --- Scheduler / motore alert ---
    # In produzione gira nel processo dedicato ``python -m app.worker``. Questo flag
    # lo avvia invece dentro il processo API (comodo in sviluppo, una sola replica).
    scheduler_enabled: bool = False
    imminent_interval_s: int = 15
    strike_interval_s: int = 3600
    service_alert_interval_s: int = 300  # avvisi di servizio (deviazioni) per linea

    # --- Push (FCM/APNs via Firebase Admin SDK) ---
    # Abilitato solo quando c'è una service account key valida (config esterna).
    fcm_enabled: bool = False
    fcm_credentials_file: str = "secrets/firebase-admin.json"
    # In alternativa al file: il contenuto JSON della service account (hosting senza disco).
    # Se valorizzato ha la precedenza su ``fcm_credentials_file``.
    fcm_credentials_json: str = ""
    # Intervallo con cui svuotare la coda del dispatcher e inviare le push.
    push_interval_s: int = 10

    # --- WebSocket mappa ---
    # Ogni quanto spingere le posizioni dei mezzi (legge dalla cache RT condivisa).
    ws_interval_s: float = 4.0
    # Tetto di connessioni WS simultanee (backpressure).
    ws_max_connections: int = 500

    # --- Keep-alive (hosting free che spegne il servizio senza traffico in ingresso) ---
    # Se valorizzato, lo scheduler chiama ``<url>/health`` ogni ``keepalive_interval_s``.
    # Su Render viene letto in automatico da RENDER_EXTERNAL_URL.
    keepalive_url: str = Field(
        default="", validation_alias=AliasChoices("TT_KEEPALIVE_URL", "RENDER_EXTERNAL_URL")
    )
    keepalive_interval_s: int = 600


@lru_cache
def get_settings() -> Settings:
    """Istanza singleton delle settings (cache per processo)."""
    return Settings()

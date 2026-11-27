# Transito Torino — backend

API (FastAPI) e worker per il trasporto pubblico GTT di Torino: arrivi in fermata, posizioni
live dei mezzi, avvisi e scioperi, preferiti e alert push. Contratto API in `../SPEC.md`,
sorgenti dati e trappole note in `../docs/DATA_SOURCES.md`.

## Sviluppo

```bash
cd backend
uv sync --extra dev                       # dipendenze bloccate in uv.lock
.venv/bin/uvicorn app.main:app --reload   # docs: http://127.0.0.1:8000/docs
.venv/bin/pytest                          # nessun test tocca la rete o dipende dall'orologio
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Default di sviluppo: SQLite (`./transito.db`) e cache in memoria, nessun servizio esterno.
Configurazione con variabili `TT_*` (vedi `.env.example`); gli URL delle sorgenti stanno solo
in `app/config.py`.

## Endpoint

Tutto sotto `/v1`, tranne `/health`.

- `GET /health` — `status` `ok`|`degraded`, età del GTFS, DB, cache
- `GET /v1/lines`, `GET /v1/lines/{line}/vehicles`, `GET /v1/lines/{line}/shape`
- `GET /v1/stops/search?q=&limit=`, `GET /v1/stops/{stop_id}/arrivals?line=`
- `GET /v1/alerts?line=` — avvisi GTT + scioperi rilevanti per Torino
- `WS /v1/ws/lines/{line}` — posizioni dei mezzi ogni ~4 s dalla cache condivisa
- `/v1/me/*` — device, preferiti, sottoscrizioni alert

Identità: `POST /v1/me/devices` con `{platform, token}` restituisce `id` e `secret`; le altre
chiamate `/me/*` richiedono gli header `X-Device-Id` e `X-Device-Secret`.

## Processi

- **API** (`uvicorn app.main:app`): scalabile su più worker/repliche.
- **Worker** (`python -m app.worker`): scheduler alert (imminent ~15 s, strike ~1 h,
  line_alert ~5 min) e invio push. **Una sola replica**, altrimenti job e push si duplicano.
  In sviluppo lo stesso scheduler può girare dentro l'API con `TT_SCHEDULER_ENABLED=true`.

Push FCM: servono `TT_FCM_ENABLED=true` e la service account in `secrets/` (vedi
`secrets/README.md` e `../docs/FIREBASE_SETUP.md`). Con FCM spento gli alert vengono valutati
e scartati con un log, senza accumularsi.

## Container e infrastruttura

```bash
# Solo Postgres + Redis (backend locale con uvicorn)
docker compose -f ../infra/docker-compose.yml up -d
export TT_DATABASE_URL=postgresql+psycopg://transito:transito@localhost:5432/transito
export TT_REDIS_URL=redis://localhost:6379/0

# Stack completo come in produzione: API + worker in container
docker compose -f ../infra/docker-compose.yml --profile app up -d --build
```

L'immagine (`Dockerfile`) applica le migrazioni Alembic all'avvio dell'API. Migrazioni a mano:

```bash
.venv/bin/alembic upgrade head
.venv/bin/alembic revision --autogenerate -m "descrizione"
```

## Comportamento con sorgenti instabili

- GTFS statico: scaricato ogni 24 h; l'indice orari si ricostruisce al cambio di data (Europe/Rome).
- Download falliti: si serve l'ultimo dato valido e si ritenta dopo `TT_RETRY_BACKOFF_S` (300 s).
- Feed RT giù: ultimo payload valido fino a 1 h; `/v1/alerts` restituisce comunque gli scioperi.

Dati: "Città di Torino / GTT" (CC BY 4.0); arrivi "5T / Muoversi a Torino"; scioperi "Commissione di Garanzia Sciopero (CGSSE)".

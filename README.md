# Anduma

> *Anduma*, in piemontese «andiamo»: sai quando passa, sai quando andare.

App mobile per il trasporto pubblico di Torino (GTT): **arrivi in fermata in tempo
reale**, **posizione live** di bus e tram sul percorso, **preferiti** e **notifiche
push** per passaggi imminenti e scioperi. Costruita interamente su open data ufficiali.

L'obiettivo è un'app più completa e fluida delle soluzioni esistenti (MATO Live Bus,
GTT TO Move), con — elemento distintivo — gli **alert push** per il passaggio imminente
di una linea a una fermata e per gli **scioperi** che toccano Torino/Piemonte.

## Stato

| Fase | Descrizione | Stato |
|------|-------------|:-----:|
| M0–M5 | Backend: dati GTT/MIT, persistenza, preferiti, alert, push FCM, WebSocket | ✅ |
| M6–M7 | Client Flutter: Arrivi, Mappa, Preferiti, Avvisi, alert push e deep-link | ✅ |
| **H** | Consolidamento: correzioni dall'audit di ottobre 2026, preparazione al rilascio | 🔄 |
| M8 | Distribuzione (Android prima, poi iOS) | ⬜ |

Esiti e rischi per fase in [`ROADMAP.md`](ROADMAP.md); lavoro aperto della fase corrente in
[`TASKS.md`](TASKS.md).

## Architettura

```
Open data (GTFS statico + GTFS-RT GTT + registro scioperi MIT)
        │
        ▼
Backend Python (FastAPI)  ── polling centralizzato + cache TTL ──┐
  • ingestion feed (solo backend, mai dal telefono)             │
  • API REST/WebSocket                                          │
  • motore alert + scheduler → push FCM/APNs                    │
        │                                                       │
        ▼                                                       │
Client Flutter (mappa, arrivi, preferiti) ──────────────────────┘
  parla esclusivamente con la nostra API (/v1)
```

In produzione: container API + container **worker** (scheduler alert e push, una sola replica),
PostgreSQL e Redis. Stessa immagine (`backend/Dockerfile`). Per l'hosting gratuito
(un solo container su Render + PostgreSQL su Supabase) vedi [`docs/DEPLOY.md`](docs/DEPLOY.md).

**Vincolo chiave:** il polling dei feed lo fa **solo il backend**, con cache condivisa
(rate limit + batteria). I feed RT sono **protobuf binari**, non JSON.

## Stack

- **Backend**: Python 3.12, FastAPI, httpx, `gtfs-realtime-bindings` (protobuf), pydantic.
- **Cache**: in-memory in sviluppo, Redis in produzione.
- **DB**: SQLite per iniziare, PostgreSQL in produzione.
- **Scheduler**: APScheduler. **Push**: Firebase Cloud Messaging (APNs dietro FCM).
- **Client**: Flutter, mappa con `flutter_map` + tile OpenStreetMap.

## Avvio rapido

```bash
# Backend (SQLite + cache in memoria, nessun servizio esterno)
cd backend
uv sync --extra dev                # oppure: python -m venv .venv && pip install -e ".[dev]"
.venv/bin/uvicorn app.main:app --reload   # docs interattive: http://127.0.0.1:8000/docs
.venv/bin/pytest                   # nessun test tocca la rete
.venv/bin/ruff check . && .venv/bin/ruff format --check .

# Stack completo in container (Postgres, Redis, API, worker)
docker compose -f infra/docker-compose.yml --profile app up -d --build

# Mobile
cd mobile
flutter run --dart-define=TT_API_BASE=http://10.0.2.2:8000   # emulatore Android
```

Endpoint e contratto API in [`SPEC.md`](SPEC.md); dettagli del backend in
[`backend/README.md`](backend/README.md), del client in [`mobile/README.md`](mobile/README.md).

## Struttura del repo

```
.
├── AGENTS.md            # istruzioni per gli agenti di sviluppo (CLAUDE.md vi rimanda)
├── SPEC.md              # requisiti e contratto API
├── ROADMAP.md           # fasi, esiti, rischi
├── TASKS.md             # fase corrente e lavoro aperto
├── docs/                # DATA_SOURCES, FIREBASE_SETUP, DESIGN_PROMPTS
├── backend/             # FastAPI + worker + test (vedi backend/README.md)
├── mobile/              # client Flutter (vedi mobile/README.md)
└── infra/               # docker-compose
```

## Sviluppato con Claude Code

Questo progetto è sviluppato con l'assistenza di **[Claude Code](https://claude.com/claude-code)**,
la CLI agentica di Anthropic. Scaffolding del backend, parser dei feed, suite di test e
documentazione sono stati prodotti iterativamente in coppia con l'agente, seguendo le
milestone di [`ROADMAP.md`](ROADMAP.md) (un branch e una review per fase).
Il file [`AGENTS.md`](AGENTS.md) fornisce all'agente il contesto, lo stack e i vincoli
non negoziabili del progetto.

## Dati e licenze

- **Feed GTT** (GTFS statico + Realtime): **CC BY 4.0** → credito *"Città di Torino / GTT"*.
- **Arrivi in tempo reale**: **5T / Muoversi a Torino** (dati aperti, art. 52 CAD) → credito *"5T / Muoversi a Torino"*.
- **Scioperi**: dati **MIT — Osservatorio sui Conflitti Sindacali**.
- **Mappa**: tile **OpenStreetMap** → *"© OpenStreetMap contributors"*.

Tutte le sorgenti, con formati e trappole note, sono documentate in
[`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md). I crediti sono nella schermata
"Informazioni" dell'app (icona ⓘ in alto). Font Manrope: SIL Open Font License 1.1.

## Licenza

Codice: MIT. I dati restano soggetti alle rispettive licenze sopra.

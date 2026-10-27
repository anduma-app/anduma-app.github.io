# ROADMAP — Transito Torino

Esiti ordinati per fase, con rischi e criteri di uscita. Il dettaglio operativo della fase
corrente è in `TASKS.md`; requisiti e contratto API in `SPEC.md`.

## Fasi completate (M0–M7)

| Fase | Esito |
|------|-------|
| M0 | Backend read-only: linee, ricerca fermate, arrivi RT, mezzi, avvisi GTT + scioperi MIT. |
| M1 | Persistenza: SQLAlchemy + Alembic, Postgres/Redis via docker-compose, cache astratta. |
| M2 | Device anonimo, preferiti e sottoscrizioni (`/me/*`). |
| M3 | Motore alert (imminent, strike, line_alert) con APScheduler e dedup in `notified_events`. |
| M4 | Push FCM (Firebase Admin SDK) con cleanup dei token. |
| M5 | `WS /ws/lines/{line}` dalla cache RT condivisa, fallback polling REST. |
| M6 | Client Flutter: Arrivi, Mappa, Preferiti, Avvisi, Info. |
| M7 | Push lato client, gestione alert dai preferiti, deep-link, percorso linea sulla mappa, fermate omonime disambiguate. |

Le fasi M0–M7 sono state scritte con versioni precedenti degli agenti. L'audit di ottobre 2026
ha trovato bug reali e lacune di rilascio: prima di distribuire serve la fase H.

## H — Consolidamento (corrente)

Esito: codice corretto e verificabile, pronto per essere distribuito.

- Backend: test senza rete né orologio, arrivi corretti a cavallo del giorno di servizio,
  refresh delle sorgenti robusto, dedup e push affidabili, logging e health utili.
- Mobile: aggiornamenti dei preferiti, crediti raggiungibili, niente stream o timer attivi
  in background, riconnessione WS, flusso permessi notifiche corretto.
- Rilascio: `/me/*` non enumerabile, prefisso `/v1`, immagine container, build release
  Android firmabile senza `google-services.json`, font e tile conformi alle policy.

**Fatto quando**: `pytest` (backend, offline) e `flutter analyze && flutter test` verdi;
app verificata su emulatore Android contro backend locale; nessun P0/P1 aperto in `TASKS.md`.

## M8 — Distribuzione (Android prima)

- Backend in container su un host gestito: API + processo scheduler separato (una sola replica),
  Postgres, Redis, migrazioni all'avvio, monitoraggio di base (health + log).
- Play Store: nome definitivo, icona, privacy policy, scheda, crediti dati; Internal Testing.
- iOS dopo, con build su CI macOS (Xcode completo non installabile in locale per spazio).

**Fatto quando**: un tester installa l'app da Play Internal Testing, vede arrivi reali e
riceve una push di alert.

## Dopo (non pianificato)

- Ricerca fermate ordinata per vicinanza (permesso posizione).
- Mini-mappa / tap-per-mappa sul risultato di ricerca.
- Reminder sciopero il giorno prima e il mattino stesso; avviso sciopero anche a chi ha solo preferiti.
- Statistiche di puntualità, stima congestione da `shapes.txt`, pianificazione viaggio (OpenTripPlanner).

## Rischi

- **URL sorgenti**: il link dello ZIP GTFS statico e le colonne del CSV MIT cambiano senza preavviso.
  Mitigazione: URL solo in `config.py`, parser difensivi, log e health che segnalano dati vecchi.
- **Tile OSM**: la policy di `tile.openstreetmap.org` vieta l'uso intensivo da app senza cache e
  User-Agent identificativo. Con molti utenti serve un provider di tile dedicato.
- **Costo operativo**: un manutentore singolo; preferire servizi gestiti e un solo container.
- **iOS**: richiede Xcode (decine di GB) o CI macOS; rimandato a dopo Android.
- **Store**: `applicationId` (`it.anduma.transito`) e nome diventano permanenti alla prima pubblicazione.

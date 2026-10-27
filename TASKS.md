# TASKS — fase H (Consolidamento)

Fonte: audit del 2026-10-27 (backend e mobile), voci verificate sul codice e sui dati reali.
Priorità: P0 bug che produce dati errati o blocca, P1 importante prima del rilascio, P2 miglioria.

## Stato validazione (2026-10-27)

- Backend: `pytest` 85/85 in <1 s, offline e senza dipendenza dall'orologio; `ruff check` e
  `ruff format --check` puliti; migrazioni Alembic su/giù verificate; `alembic check` senza drift.
- Backend su dati reali: arrivi, avvisi (con feed GTT in errore 500), scioperi dal feed RSS MIT.
- Container: stack completo (Postgres, Redis, API, worker) avviato su Colima; `/health` ok.
- Mobile: `flutter analyze` pulito, `flutter test` 5/5 offline; build debug Android con e senza
  `google-services.json`; verificata su emulatore Pixel 9 API 35 (ricerca, arrivi, preferiti,
  mappa, permesso notifiche al primo alert, consentito e negato).
- Push FCM reale su emulatore: banner ad app in background (canale ad alta importanza, icona di
  stato), tocco sulla notifica → Arrivi della fermata.
- Non verificata: build release firmata.

## Fatto

Documentazione
- [x] `AGENTS.md` con sezione progetto; `ROADMAP.md`, `SPEC.md`, `TASKS.md` alla radice; README,
      `backend/README.md`, `mobile/README.md`, `DATA_SOURCES.md`, `FIREBASE_SETUP.md` allineati.

Backend
- [x] P0 Arrivi errati dopo il cambio di giorno (indice orari fissato al giorno del caricamento) e
      nei giorni del cambio d'ora: base da `start_date` RT, "mezzogiorno − 12 h", corse di ieri incluse.
- [x] P0 Scioperi: il CSV MIT è fermo al 2020 → feed RSS; filtro di rilevanza per GTT.
- [x] P1 Previsioni assenti oltre le ~7 fermate pubblicate da GTT → ritardo propagato (GTFS-RT).
- [x] P1 Test con rete reale nel lifespan; test dipendente dalla data.
- [x] P1 Refresh GTFS/scioperi con lock e backoff; ultimo dato valido se la sorgente è giù.
- [x] P1 Coda push illimitata con FCM spento; dedup senza vincolo né pulizia; push doppie per device.
- [x] P1 `/me/*` enumerabile → segreto per device; aggiornamento token FCM; prefisso `/v1`.
- [x] P1 Logging, `/health` con stato `degraded`; worker separato; Dockerfile, `uv.lock`, `apscheduler<4`.
- [x] P2 Token non validi (`INVALID_ARGUMENT`); WS che si chiudeva su errore upstream;
      registrazioni concorrenti; sottoscrizioni duplicate; `ruff format`.

Mobile
- [x] P0 Arrivi dei preferiti mai aggiornati; card senza key; Info (crediti CC BY) irraggiungibile;
      URL backend inutilizzabile fuori da web/desktop.
- [x] P1 Risposte fuori ordine; stream e timer in background; WS mai ricollegato; stessa fermata
      non riapribile; deep-link Avvisi; permesso notifiche (richiesta al primo alert, esito rispettato).
- [x] P1 Release Android: cleartext solo debug, google-services opzionale, firma da `key.properties`,
      nome "Transito Torino"; Manrope inclusa; flutter_map 8 con cache tile.
- [x] P2 Test del client API senza rete; piattaforma reale nella registrazione.
- [x] P1 Push fuori dall'app poco visibili e ritardabili: canale Android ad alta importanza con
      icona di stato, invio FCM a priorità alta.

## Da fare

- [ ] P1 Icona dell'app (oggi quella di default di Flutter) e nome definitivo.
- [ ] P1 Privacy policy (l'app invia token FCM e id device) e scheda Play Store.
- [ ] P1 Build release firmata; push end-to-end da un alert reale su telefono.
- [ ] P2 Firebase: firebase_core 5 / firebase_messaging 17.
- [ ] P2 Pulsante "posizione" che ricentra solo su Torino.
- [ ] P2 Strike card: una sola data se inizio = fine (il dettaglio completo è in ROADMAP).
- [ ] P2 Numero di palina (quello esposto alla fermata, es. 253) accanto al nome nelle card dei
      Preferiti, per distinguere le fermate omonime.
- [ ] P2 Fermata aperta da notifica: l'intestazione mostra lo `stop_id` (es. 1687) invece del
      numero di palina (253).
- [ ] P2 Dead code segnalato dall'audit: `TransitLine.mode` duplicato, `cupertino_icons` inutilizzato,
      commento su sync preferiti in `favorites_store.dart`, versione "v0.1 (MVP)" fissa in Info.

## Decisioni aperte (utente)

- Hosting del backend per M8 (servono container API + worker, Postgres, Redis).
- Nome definitivo dell'app e `applicationId` prima della pubblicazione.
- Provider di tile se l'app supera l'uso consentito dai server OSM.
- Versionare `AGENTS.md` e `CLAUDE.md` (oggi `CLAUDE.md` è in `.gitignore`, `AGENTS.md` non è tracciato).

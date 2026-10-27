# TASKS — fase H (Consolidamento)

Fonte: audit del 2026-10-27 (backend e mobile), voci verificate sul codice.
Priorità: P0 bug che produce dati errati o blocca, P1 importante prima del rilascio, P2 miglioria.

## Stato validazione

- Backend: `pytest` 71/71 verdi (dopo fix del test sugli scioperi dipendente dalla data);
  `ruff check` pulito; `ruff format --check` segnala 4 file.
- Mobile: `flutter analyze` pulito; `flutter test` verde ma lo smoke test usa la rete (tile OSM, font).
- Toolchain locale: Flutter 3.44.1, Android SDK + AVD `Pixel_9_API35`, Colima. Mancano Xcode
  completo e CocoaPods (solo iOS). La cache Gradle è vuota: la prima build Android la riscarica.

## Documentazione

- [x] `AGENTS.md` con sezione progetto aggiornata; `ROADMAP.md` e `TASKS.md` alla radice; backlog nella roadmap.
- [ ] `SPEC.md`: kind `line_alert`, endpoint `/lines/{line}/shape`, uso di `stop_times.txt`, auth device.
- [ ] README di radice, backend e mobile allineati allo stato reale.

## Backend

- [ ] P0 Calendario GTFS fissato al giorno del caricamento e tenuto 24 h: il mattino dopo gli
      arrivi da soli ritardi risultano nel passato e spariscono. Ricostruire al cambio di giorno
      di servizio, includere le corse oltre mezzanotte del giorno prima, base "mezzogiorno − 12 h" per DST.
- [ ] P1 I test del `client` eseguono il lifespan che scarica il GTFS reale (rete nei test, ~5 s a test).
- [ ] P1 Refresh GTFS/scioperi senza lock né backoff: con sorgente giù ogni richiesta ritenta un
      download da 15 s; download paralleli dello ZIP alla scadenza del TTL.
- [ ] P1 Con scheduler attivo e FCM spento la coda del dispatcher cresce senza limite.
- [ ] P1 `notified_events` senza vincolo unico né pulizia delle righe scadute.
- [ ] P1 Sciopero/avviso notificato più volte allo stesso device se ha più sottoscrizioni di linea.
- [ ] P1 `X-Device-Id` intero sequenziale senza segreto: `/me/*` enumerabile. Serve un segreto
      per device e un endpoint di aggiornamento del token FCM.
- [ ] P1 Nessun log; errori ingoiati; `/health` sempre `ok`.
- [ ] P1 Deploy: Dockerfile, lockfile, `apscheduler<4`, migrazioni all'avvio, scheduler in processo separato.
- [ ] P1 Prefisso `/v1` (SPEC §4), insieme al client.
- [ ] P2 Token FCM non validi non rimossi (`InvalidArgumentError` non gestito); invio uno a uno.
- [ ] P2 WS: un errore upstream chiude la connessione invece di saltare il tick; parse ripetuti per connessione.
- [ ] P2 Registrazione device concorrente → 500; sottoscrizioni duplicate ammesse.
- [ ] P2 `ruff format` sui 4 file segnalati.

## Mobile

- [ ] P0 Preferiti: gli arrivi delle card non si aggiornano mai (timer e pull-to-refresh non rifanno la richiesta).
- [ ] P0 Preferiti: `_StopCard` senza key, dopo una rimozione una card mostra gli arrivi di un'altra fermata.
- [ ] P0 Pulsante Info in un `AppBar` alto 0: schermata crediti (obbligo CC BY) irraggiungibile.
- [ ] P0 URL backend di default `127.0.0.1`: inutilizzabile su emulatore, device e release.
- [ ] P1 Arrivi: risposta tardiva della fermata precedente sovrascrive quella corrente; ricerca fuori ordine.
- [ ] P1 Mappa costruita all'avvio (WS e tile anche se mai aperta); stream e timer attivi in background.
- [ ] P1 WS mai ricollegato dopo il fallback a polling; badge "in pausa" all'avvio.
- [ ] P1 Riaprire la stessa fermata da mappa/push non fa nulla (`ValueNotifier` mai azzerato).
- [ ] P1 Permessi notifiche: esito ignorato, richiesta a freddo al primo avvio, registrazione mai ritentata.
- [ ] P1 Deep-link ad Avvisi: dati non ricaricati e non filtrati per linea.
- [ ] P1 Release: firma debug, `usesCleartextTraffic` anche in release, plugin google-services
      obbligatorio (un clone pulito non compila), nome "transito", icona Flutter di default.
- [ ] P1 `google_fonts` scarica Manrope a runtime: includere i font nell'app.
- [ ] P1 Tile OSM: User-Agent, cache persistente (flutter_map 8), attribuzione visibile.
- [ ] P2 Test senza rete; test per modelli, `ApiClient`, stores.
- [ ] P2 Pulsante "my_location" che ricentra solo su Torino; piattaforma `android` fissa; canale notifiche di default.
- [ ] P2 Aggiornare firebase_core 5 / firebase_messaging 17.

## Decisioni aperte (utente)

- Hosting del backend per M8.
- Nome definitivo dell'app e `applicationId` prima della pubblicazione.
- Versionare `AGENTS.md` e `CLAUDE.md` (oggi `CLAUDE.md` è in `.gitignore`).

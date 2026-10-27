# SPEC — Transito Torino

Specifica prodotto e tecnica. Riferimento per implementazione e test.

## 1. Obiettivo

App mobile per muoversi col trasporto pubblico GTT a Torino, più completa delle soluzioni
esistenti (MATO Live Bus, GTT TO Move): mappa mezzi fluida, arrivi in tempo reale, preferiti
e — elemento distintivo — notifiche push per passaggi imminenti e per scioperi.

## 2. Funzionalità

### MVP
1. **Ricerca fermata** per nome o codice palina.
2. **Arrivi in fermata** in tempo reale (linea, capolinea, minuti all'arrivo), auto-refresh.
3. **Mappa live** dei mezzi di una linea, con direzione di marcia.
4. **Avvisi di servizio** GTT (deviazioni/guasti) e **scioperi** che riguardano Torino/Piemonte.

### v1 (completa)
5. **Preferiti**: fermate e linee salvate, schermata "casa" con i prossimi passaggi dei preferiti.
6. **Alert passaggio imminente**: push quando un mezzo di linea X è a ≤ N minuti dalla fermata Y.
7. **Alert sciopero**: push quando viene proclamato/si avvicina uno sciopero che tocca le linee preferite.
8. **Calcolo a colpo d'occhio** della prossima corsa utile per una coppia (fermata, linea).

### Idee future (non vincolanti)
- Storicizzazione passaggi → statistiche di puntualità/regolarità per linea e tratta.
- Stima congestione/velocità per tratta dalle posizioni successive + `shapes.txt`.
- Pianificazione viaggio (richiede un routing engine, es. OpenTripPlanner sul GTFS).

## 3. Architettura (sintesi)

Sorgenti open data → **backend Python** (ingestion + cache TTL, API REST/WebSocket, motore alert,
dispatcher push, DB) → **client Flutter** (mappa, arrivi, preferiti). Le push partono dal backend
via FCM/APNs. Dettaglio sorgenti in `docs/DATA_SOURCES.md`.

Processi in produzione: API (FastAPI, scalabile) + **worker** (`python -m app.worker`, una sola
replica: scheduler alert e invio push) + PostgreSQL + Redis. Stessa immagine container.

## 4. Contratto API (REST)

Tutte le risposte sono JSON. Tutti gli endpoint REST e WS stanno sotto `/v1` (omesso qui per
brevità), tranne `GET /health` (monitoraggio: `status` `ok`|`degraded`, età GTFS, DB, cache).

### `GET /lines`
Elenco linee. → `[{ "line": "10", "description": "...", "route_ids": ["..."], "mode": "tram" }]`
(`mode` da `route_type`: tram | metro | rail | bus | ferry | funicular).

### `GET /stops/search?q={testo}&limit={n}`
Ricerca fermate. → `[{ "stop_id", "code", "name", "desc", "lat", "lon", "lines" }]`
(`desc` = via + comune, `lines` = linee della palina: distinguono le fermate omonime).

### `GET /stops/{stop_id}/arrivals?line={opt}`
Passaggi previsti in tempo reale (dai trip update GTFS-RT; ritardo propagato alle fermate
successive all'ultimo aggiornamento, come da specifica GTFS-RT).
```json
{
  "stop_id": "350",
  "name": "MASSARI CAP.",
  "arrivals": [
    { "line": "10", "headsign": "Corso Settembrini", "trip_id": "...",
      "eta_seconds": 240, "eta_minutes": 4, "scheduled_ts": 1780000000 }
  ]
}
```

### `GET /lines/{line}/vehicles`
Posizioni live dei mezzi della linea.
```json
{ "line": "10", "count": 7,
  "vehicles": [ { "vehicle_id", "trip_id", "headsign",
                  "lat", "lon", "bearing", "speed", "ts" } ] }
```

### `GET /lines/{line}/shape`
Tracciato e fermate della linea per la mappa.
→ `{ "line", "polylines": [ { "direction", "points": [[lat, lon], ...] } ], "stops": [Stop] }`

### `GET /alerts?line={opt}`
Avvisi GTT + scioperi MIT rilevanti per Torino.
```json
{ "service_alerts": [ { "header", "description", "effect", "lines": ["10"] } ],
  "service_alerts_available": true,
  "strikes": [ { "start_date", "end_date", "sector", "relevance", "area", "unions", "category" } ] }
```
Se il feed avvisi GTT non risponde: `service_alerts_available=false`, scioperi comunque presenti.

### Utenti & sottoscrizioni
- `POST /me/devices` — registra (o ri-registra) il device. Body: `{ "platform": "android|ios", "token": "<FCM>" }`
  → `{ "id", "platform", "created_at", "secret" }`. Il segreto ruota a ogni registrazione.
- `PUT /me/devices/token` — token FCM ruotato. Body: `{ "token": "..." }` (preferiti e alert restano).
- `GET|POST /me/favorites`, `DELETE /me/favorites/{id}` — preferiti `{ "type": "stop|line", "ref": "350|10" }`
- `GET|POST /me/subscriptions`, `DELETE /me/subscriptions/{id}` — alert (idempotente su kind+fermata+linea):
  ```json
  { "kind": "imminent",   "stop_id": "350", "line": "10", "threshold_min": 5 }
  { "kind": "strike",     "line": "10" }
  { "kind": "line_alert", "line": "10" }
  ```

Autenticazione: device anonimo. Le chiamate `/me/*` richiedono `X-Device-Id` + `X-Device-Secret`
(nel DB solo l'hash del segreto). Account opzionale dopo.

## 5. WebSocket (mappa fluida)

`WS /ws/lines/{line}` — il server spinge un array di posizioni ogni ~3–5 s (legge dalla cache RT,
non un fetch per connessione). Messaggio: stesso schema di `vehicles` sopra. Il client disegna/anima
i marker. Fallback: polling REST di `/lines/{line}/vehicles` se il WS non è disponibile, con nuovi
tentativi WS in backoff. Se il feed è momentaneamente giù il server salta il giro senza chiudere.

## 6. Motore alert (backend)

Scheduler APScheduler:
- **imminent** (ogni ~15 s): per ogni sottoscrizione, leggi gli arrivi previsti alla `stop_id` per la
  `line`; se `eta_minutes <= threshold_min` e non già notificato per quel `trip_id`, accoda push.
  Deduplica per `(subscription_id, trip_id)` con TTL finché il mezzo non è passato.
- **strike** (ogni ~1 h): per ogni sciopero rilevante per GTT (feed RSS MIT: TPL/generale/
  plurisettoriale, nazionale o in Piemonte/Torino), notifica una volta ogni device con
  sottoscrizioni `strike`. Da fare: reminder il giorno prima e il mattino stesso; avviso anche a
  chi ha solo preferiti.
- **line_alert** (ogni ~5 min): per ogni avviso di servizio GTT sulle linee sottoscritte, una push
  per device (anche se segue più linee coinvolte), ripetuta al più ogni 7 giorni.

Stato in DB: `notified_events` con vincolo unico `(subscription_id, dedup_key)`; righe scadute
rimosse a ogni valutazione; le valutazioni sono idempotenti.

## 7. Modello dati (DB)

- `devices(id, platform, fcm_token, secret_hash, created_at)`
- `favorites(id, device_id, type, ref)` — type ∈ {stop, line}
- `subscriptions(id, device_id, kind, stop_id?, line?, threshold_min?, active)` — kind ∈ {imminent, strike, line_alert}
- `notified_events(id, subscription_id, dedup_key, expires_at)`

## 8. Note di qualità

- Tutti i campi RT sono opzionali per spec GTFS-RT: il codice deve degradare con grazia (mezzi senza
  posizione, trip update senza orario, ecc.).
- I test usano payload protobuf/XML/ZIP salvati come fixture in `backend/tests/fixtures/`. Zero rete
  nei test, nessuna dipendenza dall'orologio (date iniettate).
- Date di servizio e "oggi" sempre in Europe/Rome. Orari GTFS da "mezzogiorno − 12 h" della data
  di servizio (`start_date` del trip), corse oltre mezzanotte incluse.
- Performance: GTFS statico scaricato ogni 24 h (ZIP tenuto in memoria), indice orari ricostruito
  al cambio di data; sorgenti giù → si serve l'ultimo dato valido e si ritenta con backoff.

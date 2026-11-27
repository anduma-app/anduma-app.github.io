# DATA_SOURCES — Transito Torino

Tutte le sorgenti, con formato, licenza e trappole note. Tenere gli URL in `backend/app/config.py`.

## GTFS statico (orari, fermate, percorsi)

- Dataset: http://aperto.comune.torino.it/dataset/feed-gtfs-trasporti-gtt
- Formato: ZIP di file `.txt` (CSV) secondo specifica GTFS.
- Licenza: **CC BY 4.0** (attribuzione "Città di Torino / GTT").
- File usati: `routes.txt`, `stops.txt`, `trips.txt`, `calendar*.txt`, `stop_times.txt`, `shapes.txt`.
- **Trappola**: il link diretto di *download* dello ZIP può cambiare. Se dà 404, riprenderlo dalla
  pagina del dataset (sezione "Dati e Risorse" → risorsa "Feed GTFS … statico"). Tenerlo in config.
- `stop_times.txt` (~110 MB) **serve**: GTT indica la fermata nei trip update con `stop_sequence`
  e quasi sempre solo col `delay`. Si indicizzano in streaming le sole corse attive ieri e oggi
  (`stop_sequence → stop_id, orario`), ~1,5 s per costruire l'indice.

### Mappatura linea → route_id (fondamentale)
I feed RT identificano le corse con `route_id`/`trip_id` interni, non con l'etichetta "10".
Per filtrare una linea: leggere `routes.txt`, prendere le righe con `route_short_name == "10"`,
raccogliere i relativi `route_id` (possono essere più d'uno per varianti di percorso).

## GTFS-Realtime (protobuf binario)

Tre endpoint, tutti formato **GTFS-RT** (protobuf, NON JSON). Parsare con `gtfs-realtime-bindings`:
`from google.transit import gtfs_realtime_pb2`.

| Feed | URL | Contenuto |
|------|-----|-----------|
| Posizioni mezzi | https://percorsieorari.gtt.to.it/das_gtfsrt/vehicle_position.aspx | `VehiclePosition`: lat/lon, bearing, speed, trip, vehicle id |
| Trip update | https://percorsieorari.gtt.to.it/das_gtfsrt/trip_update.aspx | `TripUpdate`: per ogni `stop_time_update` arrivo/partenza previsti |
| Alerts | https://percorsieorari.gtt.to.it/das_gtfsrt/alerts.aspx | `Alert`: deviazioni/avvisi, con `informed_entity` (route/stop) |

**Nota**: il server risponde solo su HTTPS (porta 443). Le URL con `http://` vanno in timeout
senza errore. La homepage `https://percorsieorari.gtt.to.it/` non risponde (normale: è un
server API puro, non un sito web). Dataset ufficiale su Open Data Torino:
https://aperto.comune.torino.it/en/dataset/feed-gtfs-real-time-trasporti-gtt

- Cache TTL consigliata: ~10–15 s per posizioni/trip update, ~60 s per gli alerts.
- Arrivi alla fermata: per ogni `TripUpdate` si risolve `stop_sequence` → `stop_id` con l'indice
  orari; l'orario è `arrival.time` se presente, altrimenti programmato + `delay`, con base
  "mezzogiorno − 12 h" della `start_date` del trip (corretto anche nei giorni del cambio d'ora).
- **Trappola**: GTT pubblica previsioni solo per le ~7 fermate successive di ogni corsa. Per le
  fermate più avanti il ritardo dell'ultimo aggiornamento si propaga (regola GTFS-RT).
- **Trappola**: il feed alerts a volte risponde 500. Il backend serve l'ultimo payload valido
  (fino a 1 h) e `/v1/alerts` restituisce comunque gli scioperi (`service_alerts_available=false`).
- Tutti i campi sono opzionali per spec: controllare sempre `HasField(...)` prima di leggere.

## Arrivi in fermata: Muoversi a Torino (5T)

Fonte principale degli arrivi (`/v1/stops/{id}/arrivals` e alert `imminent`); il feed GTT
trip update resta come ripiego se MATO non risponde o non conosce la fermata.

- Endpoint: GraphQL di OpenTripPlanner usato da muoversiatorino.it,
  https://mapi.5t.torino.it/routing/v1/routers/mat/index/graphql (POST JSON, non documentato).
- Query: `stop(id: "gtt:<palina>") { stoptimesWithoutPatterns { realtime realtimeState
  realtimeArrival serviceDay trip { gtfsId tripHeadsign route { shortName } } } }`.
  L'id è la **palina** (`stop_code`), non lo `stop_id` GTFS. Arrivo = `serviceDay + realtimeArrival`.
  `gtfsId` = `gtt:` + `trip_id` GTT. Si tengono solo `realtime: true` non `CANCELED`.
- Perché: 5T calcola le previsioni con un proprio sistema dalle posizioni dei mezzi; il feed GTT
  oltre le prime fermate propaga l'ultimo ritardo e l'errore cresce con l'anticipo. Misura del
  27/11/2026 (15:58–16:29, 14 fermate, passaggi reali dallo stream MQTT di 5T, quota di
  previsioni con errore entro 2 min):

  | Anticipo  | Feed GTT | MATO |
  |-----------|----------|------|
  | 0–5 min   | 60%      | 63%  |
  | 5–10 min  | 29%      | 57%  |
  | 10–20 min | 19%      | 43%  |
  | 20–60 min | 24%      | 22%  |

  Errore mediano a 10–20 min: −4,5 min GTT, −1,2 min MATO (negativo = previsto prima del
  passaggio). Tutti gli errori sono spostati di 1–2 min in negativo anche per il ritardo con cui
  il metodo rileva la partenza: conta il confronto tra le fonti più dei valori assoluti.
- Licenza: pubblicato da 5T (società in house del Comune) senza licenza esplicita → dati aperti
  per l'art. 52 c. 2 del CAD, che le linee guida AgID equiparano a **CC BY 4.0**: credito
  "5T / Muoversi a Torino".
- Cache: 15 s per palina (`ttl_mato_arrivals`), nessun ripiego su risposte vecchie.
- **Trappola**: la metro M1 non ha passaggi in tempo reale (solo da orario): arrivi vuoti.
- **Trappola**: interfaccia non documentata, può cambiare senza preavviso; il ripiego GTT copre i guasti.
- Altre sorgenti 5T non usate: posizioni MQTT `wss://mapi.5t.torino.it/scre` (topic
  `/<linea>/<mezzo>`, array `[lat, lon, direzione, velocità, corsa, verso, prossima_fermata, pieno]`,
  ~6 s) e mezzi in sharing dal secondo OTP `https://plan.muoversiatorino.it/otp/routers/mato/`.

## Scioperi (MIT)

- Osservatorio sui Conflitti Sindacali del MIT — fonte ufficiale, preavviso ≥ 10 giorni per legge.
- **Feed usato**: RSS degli scioperi in programma, aggiornato ogni giorno:
  https://scioperi.mit.gov.it/mit2/public/scioperi/rss
  - Ogni `<item>`: titolo `Data inizio: … - Settore: … - Rilevanza: … - Regione: … - Provincia: …`,
    descrizione con righe `Chiave: valore` separate da `<br/>` (data fine, sindacati, categoria,
    modalità), `guid` stabile (usato per la deduplica delle push).
  - Date in formato `DD/MM/YYYY`.
- **Trappola**: il CSV su dati.mit.gov.it (`…/scioperi-dei-trasporti/…/scioperi.csv`) è fermo
  a settembre 2020. Non usarlo.
- **Trappola**: chiavi e formato possono cambiare. Il parser riconosce le chiavi in modo
  case-insensitive per prefisso ed è coperto da una fixture nel formato reale.
- Consultazione umana: http://scioperi.mit.gov.it/mit2/public/scioperi
- Rilevanza per GTT: settore Trasporto pubblico locale, Generale o Plurisettoriale, se nazionale con
  regione "Italia" o in Piemonte/Torino; in Piemonte anche il Ferroviario (GTT gestisce la Torino-Ceres).
  Esclusi aereo, marittimo, merci, scioperi di altre regioni e "nazionali" registrati su un'altra regione.
- **Trappola**: il sito MIT non risponde (timeout) ai server in datacenter: né da Render
  (Francoforte) né da GitHub Actions (USA), verificato il 27/11/2026; da una rete domestica
  italiana sì. In produzione quindi niente scioperi finché non si trova un'altra via. Il download
  gira solo in background, così le richieste non aspettano il timeout.
- **Trappola**: il feed alerts GTT può restare in errore 500 per ore (pagina "Runtime Error" ASP.NET,
  vista il 27/10/2026): è un guasto lato GTT, l'app lo segnala e mostra comunque gli scioperi.

## Riepilogo licenze / crediti

- Feed GTT (statico + RT): **CC BY 4.0** → credito "Città di Torino / GTT".
- Arrivi in tempo reale: **5T / Muoversi a Torino** (art. 52 CAD, CC BY 4.0).
- Scioperi: dati **MIT — Osservatorio sui Conflitti Sindacali**.
- Mappa: tile **OpenStreetMap** → credito "© OpenStreetMap contributors".
Inserire tutti i crediti in una schermata "Informazioni / Fonti dati" dell'app.

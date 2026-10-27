# Transito Torino — client Flutter

App Android/iOS (Android prima). Parla solo con il backend del progetto (`/v1`), mai con le
sorgenti GTT/MIT. Schermate: Arrivi, Mappa (flutter_map + tile OSM), Preferiti, Avvisi, Informazioni.

## Sviluppo

```bash
cd mobile
flutter pub get
flutter analyze && flutter test        # i test non usano la rete

# URL del backend con --dart-define=TT_API_BASE=... In debug, senza override:
# emulatore Android → http://10.0.2.2:8000, web/desktop → http://127.0.0.1:8000.
flutter run                                             # emulatore Android
flutter run --dart-define=TT_API_BASE=http://192.168.1.10:8000   # telefono sulla stessa rete
flutter run -d chrome                                   # controllo UI rapido (richiede CORS o browser senza web security)
```

Il traffico `http` è consentito solo nelle build debug.

## Push

Senza `android/app/google-services.json` (non versionato) l'app compila e funziona senza push.
Con il file, il permesso notifiche viene chiesto al primo alert creato, non all'avvio.
Configurazione in [`../docs/FIREBASE_SETUP.md`](../docs/FIREBASE_SETUP.md).

## Build release (Android)

```bash
flutter build appbundle --dart-define=TT_API_BASE=https://<host-del-backend>
```

- `TT_API_BASE` è obbligatorio: una release senza si ferma all'avvio.
- Firma: `android/key.properties` (non versionato) con `storeFile`, `storePassword`, `keyAlias`,
  `keyPassword`. Senza, la release è firmata con la chiave debug (solo per prove locali).
- `applicationId` `it.anduma.transito`: diventa permanente alla prima pubblicazione.

## Note

- Font Manrope incluso in `assets/fonts/` (SIL OFL 1.1, licenza registrata nell'app).
- Tile `tile.openstreetmap.org` con User-Agent dell'app e cache persistente di flutter_map.
  La policy OSM non consente un uso intensivo da app: con molti utenti serve un provider dedicato.

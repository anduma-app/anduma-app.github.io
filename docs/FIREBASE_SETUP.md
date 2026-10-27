# Configurazione Firebase / Push (M7)

Le notifiche push usano **Firebase Cloud Messaging (FCM)**. Il file di configurazione
client (`google-services.json`) **non è versionato** (è in `.gitignore`): ognuno usa il
proprio progetto Firebase. L'app funziona anche senza — semplicemente le push restano
disattivate (`PushManager.available == false`).

## 1. Registra l'app Android su Firebase

1. Vai sulla [console Firebase](https://console.firebase.google.com/) → progetto **`anduma-bbabe`**.
2. *Impostazioni progetto* → *Le tue app* → **Aggiungi app** → **Android**.
3. **Nome pacchetto Android**: `it.anduma.transito` (deve combaciare con `applicationId`).
4. Registra l'app e **scarica `google-services.json`**.
5. Copia il file in:

   ```
   mobile/android/app/google-services.json
   ```

Il plugin Gradle `com.google.gms.google-services` viene applicato solo se il file esiste
(`android/app/build.gradle.kts`): senza, l'app compila e gira senza push.
`Firebase.initializeApp()` non richiede `firebase_options.dart` su Android: prende i valori
da questo file.

## 2. Avvia l'app

```bash
cd mobile
flutter run
```

Da *Preferiti* crea un alert (campana): al primo alert l'app chiede il permesso notifiche,
ottiene il token FCM e registra il device sul backend (`POST /v1/me/devices`, che restituisce
le credenziali del device). Se il permesso c'è già, la registrazione avviene a ogni avvio.

## 3. Backend: abilita l'invio push

Il backend invia le push solo se FCM è abilitato **e** lo scheduler gira. Serve la
service account key (anch'essa **non versionata**) in `backend/secrets/firebase-admin.json`
(*Impostazioni progetto* → *Account di servizio* → *Genera nuova chiave privata*).

Variabili d'ambiente (prefisso `TT_`):

```bash
export TT_FCM_ENABLED=true
export TT_FCM_CREDENTIALS_FILE=secrets/firebase-admin.json
python -m app.worker                      # scheduler + push (una sola istanza)
uvicorn app.main:app --port 8000          # API, in un altro terminale
```

In sviluppo basta un processo: `TT_SCHEDULER_ENABLED=true uvicorn app.main:app`.

## 4. Provare il deep-link

- **Alert "in arrivo"** (imminent): crea l'alert su una fermata con una linea che sta per
  passare; alla notifica, il tap apre **Arrivi** sulla fermata giusta.
- **Alert di linea** (strike/line_alert): dalla campana su una linea preferita attiva
  *Scioperi* e/o *Avvisi e deviazioni*; alla notifica il tap apre **Avvisi** filtrati sulla linea.

Per un test rapido senza aspettare il feed reale, si può inviare un messaggio di prova dalla
console FCM (*Messaggi*) al token del device, includendo nei *dati personalizzati* le chiavi
`kind` (`imminent`/`strike`), `stop_id`, `line` — sono le stesse che usa il backend
(`app/alerts.py`).

## Emulatore

Il deep-link e la registrazione token funzionano sull'emulatore con **Google Play**.
In debug l'app usa già `http://10.0.2.2:8000` sull'emulatore Android
(vedi `lib/api/config.dart`, override con `--dart-define=TT_API_BASE=...`).

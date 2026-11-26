# Deploy gratuito: Render + Supabase

Backend in un solo container sul piano free di Render, con API e scheduler alert/push
nello stesso processo. PostgreSQL gratuito su Supabase. Niente Redis né worker separato.
La configurazione è in [`render.yaml`](../render.yaml).

## Perché questi servizi

- **Render free**: 512 MB di RAM e 0,1 CPU. Il backend arriva a circa 250 MB di picco
  (misurato a novembre 2026 con il GTFS reale e lo scheduler attivo). Il servizio si spegne
  dopo 15 minuti senza traffico in ingresso: lo scheduler chiama da solo
  `RENDER_EXTERNAL_URL/health` ogni 10 minuti (`TT_KEEPALIVE_URL`, job `keepalive`).
  Le 750 ore mensili gratuite coprono un solo servizio acceso 24/7.
- **Supabase free**: database sempre acceso, 500 MB. Neon non va bene: il motore alert
  interroga il DB ogni 15 s, quindi il calcolo non va mai in pausa e supera le 100 ore
  mensili del piano free. Il Postgres free di Render scade dopo 30 giorni.

## Procedura (una tantum)

### 1. Supabase

1. Crea un progetto su <https://supabase.com>, regione **Central EU (Frankfurt)**.
   Usa una password solo alfanumerica (evita di doverla codificare nell'URL).
2. **Connect** → **Session pooler** → copia la stringa `postgresql://postgres.<ref>:[YOUR-PASSWORD]@aws-…pooler.supabase.com:5432/postgres`
   e sostituisci `[YOUR-PASSWORD]`.
   Non usare la "Direct connection" (solo IPv6) né il "Transaction pooler" (porta 6543).

Il prefisso `postgresql://` va bene così: l'app forza da sola il driver psycopg 3.
Le tabelle le crea il container al primo avvio (`alembic upgrade head`).

### 2. Credenziali Firebase

Copia negli appunti il JSON della service account su una riga sola:

```bash
python3 -c "import json;print(json.dumps(json.load(open('backend/secrets/firebase-admin.json'))))" | pbcopy
```

### 3. Render

1. Il `render.yaml` deve essere sul branch `main` di GitHub.
2. <https://dashboard.render.com> → **New** → **Blueprint** → collega il repo `anduma`.
3. Alla richiesta delle variabili incolla:
   - `TT_DATABASE_URL`: la stringa di Supabase;
   - `TT_FCM_CREDENTIALS_JSON`: il JSON copiato al passo 2.
4. **Apply**. Il primo build richiede qualche minuto; poi verifica:

```bash
curl https://transito-torino.onrender.com/health
# atteso: "status":"ok", "gtfs_loaded":true, "db":true
```

Se il nome `transito-torino` è già preso, Render aggiunge un suffisso: usa l'URL mostrato
nella dashboard.

### 4. App

```bash
cd mobile
flutter build appbundle --dart-define=TT_API_BASE=https://transito-torino.onrender.com
```

### 5. Web app (opzionale, comoda per provare senza APK)

Il workflow [`.github/workflows/web.yml`](../.github/workflows/web.yml) compila il client
Flutter per il web e lo pubblica su GitHub Pages a ogni push su `main` che tocca `mobile/`:
<https://emanueledri.github.io/anduma/>. Il backend ammette quell'origine con
`TT_CORS_ORIGINS` (impostata in `render.yaml`).

Da smartphone: apri il link e usa "Aggiungi a schermata Home". I preferiti restano salvati nel
browser.

Push web: app Web "Transito web" nel progetto Firebase, configurazione in
`mobile/lib/api/firebase_web_config.dart` e `mobile/web/firebase-messaging-sw.js` (stessi valori,
pubblici), chiave VAPID dai "Certificati push web" di Cloud Messaging. Il browser si registra
come device `web`. Su iPhone funzionano solo con la web app aggiunta alla schermata Home
(iOS 16.4+).

### 5b. Dominio anduma.is-a.dev (opzionale)

Sottodominio gratuito di [is-a.dev](https://docs.is-a.dev/guides/github-pages/): una pull
request su `is-a-dev/register` con il file `domains/anduma.json` (owner = account GitHub,
record `CNAME` = `emanueledri.github.io`). Solo **dopo** il merge: repo `anduma` →
Settings → Pages → Custom domain `anduma.is-a.dev` → Save, poi "Enforce HTTPS", e rilancio
del workflow "Web app". Il base href si adegua da solo (`actions/configure-pages`: `/anduma/`
senza dominio, `/` con il dominio); `TT_CORS_ORIGINS` ammette già `https://anduma.is-a.dev`.
Il vecchio indirizzo `emanueledri.github.io/anduma/` reindirizza al dominio.

### 6. Feedback come issue GitHub (opzionale)

Ogni feedback inviato dall'app viene salvato nella tabella `feedback` di Supabase. Se su
Render è impostato `TT_GITHUB_TOKEN`, dopo aver risposto all'app il backend apre anche una
issue su `TT_GITHUB_REPO` con etichetta `feedback`: titolo con le prime parole, messaggio
in un blocco di codice (niente @menzioni né formattazione dell'utente), piattaforma e data.
L'email (`contact`) resta solo nel database perché il repo è pubblico. Se GitHub fallisce,
il feedback resta salvato e l'errore compare solo nei log ("Issue GitHub per il feedback
non creata"). Anti-spam: `TT_FEEDBACK_MAX_PER_MINUTE` invii al minuto per IP (default 3),
con l'IP letto da `CF-Connecting-IP` (`TT_CLIENT_IP_HEADER`).

Token: GitHub → Settings → Developer settings → Personal access tokens → **Fine-grained
tokens** → Generate new token. Repository access: **Only select repositories** → `anduma`.
Repository permissions: **Issues: Read and write** (Metadata in sola lettura si aggiunge da
solo). Su Render: servizio `transito-torino` → **Environment** → aggiungi `TT_GITHUB_TOKEN`
→ **Save, rebuild, and deploy**. Alla scadenza del token va rigenerato e sostituito.

## Esercizio

- Ogni push su `main` rideploya. Il DB è su Supabase, quindi dispositivi e preferiti restano.
- Dopo un riavvio il primo `/health` può impiegare circa un minuto (download e parsing del GTFS
  con 0,1 CPU).
- Non aumentare le istanze: lo scheduler gira nel processo API e i job si duplicherebbero.
- Supabase mette in pausa i progetti free inattivi per una settimana. Con lo scheduler che
  interroga il DB ogni 15 s non dovrebbe succedere. Se succede, riattiva il progetto dalla
  dashboard.

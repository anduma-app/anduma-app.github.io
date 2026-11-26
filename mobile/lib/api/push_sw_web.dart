// Web: registra il service worker delle push e attende che sia attivo.
// Senza questa attesa la prima iscrizione push fallisce ("no active Service
// Worker") perché il worker appena registrato è ancora in installazione.
import 'dart:js_interop';

import 'package:web/web.dart' as web;

Future<void> ensurePushServiceWorker() async {
  final sw = web.window.navigator.serviceWorker;
  // Path relativo alla pagina: l'app non è servita dalla radice del dominio.
  await sw.register('firebase-messaging-sw.js'.toJS).toDart;
  await sw.ready.toDart.timeout(const Duration(seconds: 20));
}

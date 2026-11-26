// Service worker delle push web (Firebase Cloud Messaging).
// Registrato da lib/api/push_manager.dart; la configurazione qui sotto deve
// coincidere con lib/api/firebase_web_config.dart.

// Tap sulla notifica: porta in primo piano l'app (o la apre). Registrato prima
// dell'SDK Firebase, che senza un link non apre nulla.
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const scope = self.registration.scope;
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
      for (const c of list) {
        if (c.url.startsWith(scope) && 'focus' in c) return c.focus();
      }
      return clients.openWindow(scope);
    }),
  );
});

// Versione allineata a firebase_core_web (supportedFirebaseJsSdkVersion).
importScripts('https://www.gstatic.com/firebasejs/12.14.0/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/12.14.0/firebase-messaging-compat.js');

const firebaseConfig = {
  apiKey: 'AIzaSyBQVHFqjxP-JGdHxJ2WueiAAV8KD0sKdzA',
  authDomain: 'anduma-bbabe.firebaseapp.com',
  projectId: 'anduma-bbabe',
  storageBucket: 'anduma-bbabe.firebasestorage.app',
  messagingSenderId: '943541949922',
  appId: '1:943541949922:web:e5300d8b3deffd7caa95bb',
};

firebase.initializeApp(firebaseConfig);
// Il backend invia un payload `notification`: l'SDK mostra la notifica da solo.
firebase.messaging();

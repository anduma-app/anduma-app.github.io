// Configurazione Firebase del client web (push via browser).
//
// Valori pubblici per costruzione (finiscono comunque nel JavaScript servito):
// Firebase console → Impostazioni progetto → Le tue app → app Web, e la chiave
// VAPID da Cloud Messaging → Certificati push web. Devono coincidere con quelli
// in web/firebase-messaging-sw.js.
import 'package:firebase_core/firebase_core.dart';

const FirebaseOptions firebaseWebOptions = FirebaseOptions(
  apiKey: 'AIzaSyBQVHFqjxP-JGdHxJ2WueiAAV8KD0sKdzA',
  authDomain: 'anduma-bbabe.firebaseapp.com',
  projectId: 'anduma-bbabe',
  storageBucket: 'anduma-bbabe.firebasestorage.app',
  messagingSenderId: '943541949922',
  appId: '1:943541949922:web:e5300d8b3deffd7caa95bb',
);

const String firebaseWebVapidKey =
    'BGQUH0gA2XBqTZW0C2bvuR9JYrkzmry4oJabSj9ZlFv4FETBbnur1fp9BkkhPyCrfY-JXzfq6KDJw71cQ_cEMjw';

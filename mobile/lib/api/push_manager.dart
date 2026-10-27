// Gestione push (M7): init Firebase, permessi, registrazione device col token
// FCM, deep-link al tap della notifica, banner per i messaggi in foreground.
//
// Tutto è best-effort e degrada con grazia: se Firebase non è configurato
// (manca google-services.json) o i permessi sono negati, l'app continua a
// funzionare senza push — `available` resta false e nessuna funzione lancia.
import 'dart:async';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api_client.dart';

/// Destinazione di navigazione derivata dal payload `data` di una push.
class AppDeepLink {
  final String kind; // 'imminent' | 'strike' | 'line_alert'
  final String? stopId;
  final String? line;
  const AppDeepLink({required this.kind, this.stopId, this.line});

  factory AppDeepLink.fromData(Map<String, dynamic> data) => AppDeepLink(
        kind: (data['kind'] as String?) ?? '',
        stopId: data['stop_id'] as String?,
        line: data['line'] as String?,
      );
}

/// Handler dei messaggi in background/terminato. Il backend invia un payload
/// `notification`, quindi il sistema mostra la notifica da solo: qui non serve
/// fare nulla, ma l'handler va registrato (requisito di firebase_messaging).
@pragma('vm:entry-point')
Future<void> firebaseBackgroundHandler(RemoteMessage message) async {}

class PushManager {
  PushManager(this._api);

  final ApiClient _api;
  static const _deviceIdKey = 'tt_device_id_v2';
  static const _deviceSecretKey = 'tt_device_secret_v2';

  /// True se Firebase si è inizializzato: le push sono possibili su questo device.
  bool available = false;

  /// Diventa true quando il device è registrato sul backend (credenziali pronte).
  final ValueNotifier<bool> registered = ValueNotifier(false);

  /// Deep-link in attesa di essere consumato dalla UI (tap su notifica).
  final ValueNotifier<AppDeepLink?> deepLink = ValueNotifier(null);

  /// Ultimo messaggio ricevuto in foreground (per un banner in-app).
  final ValueNotifier<RemoteMessage?> foreground = ValueNotifier(null);

  bool _registering = false;

  /// Inizializza Firebase + FCM. Idempotente, non lancia mai.
  ///
  /// Non chiede il permesso notifiche: lo fa [enable] quando l'utente crea il
  /// primo alert. Se il permesso c'è già, registra il device in background.
  Future<void> init() async {
    // 1) Credenziali già salvate: header pronti subito.
    final prefs = await SharedPreferences.getInstance();
    final id = prefs.getInt(_deviceIdKey);
    final secret = prefs.getString(_deviceSecretKey);
    if (id != null && secret != null) {
      _api.deviceId = id;
      _api.deviceSecret = secret;
      registered.value = true;
    }

    // 2) Firebase: se non configurato, si resta senza push.
    try {
      await Firebase.initializeApp();
      available = true;
    } catch (e) {
      debugPrint('Push disabilitate (Firebase non configurato): $e');
      return;
    }

    final fm = FirebaseMessaging.instance;
    FirebaseMessaging.onBackgroundMessage(firebaseBackgroundHandler);
    fm.onTokenRefresh.listen(_onTokenRefresh);
    FirebaseMessaging.onMessage.listen((m) => foreground.value = m);
    FirebaseMessaging.onMessageOpenedApp.listen(_handleOpened);
    final initial = await fm.getInitialMessage();
    if (initial != null) _handleOpened(initial);

    final settings = await fm.getNotificationSettings();
    if (_granted(settings.authorizationStatus)) {
      unawaited(_registerWithRetry());
    }
  }

  /// Chiede il permesso notifiche (se serve) e registra il device.
  /// Ritorna true se le push sono attive.
  Future<bool> enable() async {
    if (!available) return false;
    final settings = await FirebaseMessaging.instance.requestPermission();
    if (!_granted(settings.authorizationStatus)) return false;
    if (!_api.hasDevice || !registered.value) await _registerOnce();
    return _api.hasDevice;
  }

  static bool _granted(AuthorizationStatus s) =>
      s == AuthorizationStatus.authorized || s == AuthorizationStatus.provisional;

  /// Registra a ogni avvio (ruota il segreto); ritenta se il backend non risponde.
  Future<void> _registerWithRetry() async {
    const delays = [Duration.zero, Duration(seconds: 10), Duration(minutes: 1), Duration(minutes: 5)];
    for (final d in delays) {
      await Future<void>.delayed(d);
      if (await _registerOnce()) return;
    }
  }

  Future<bool> _registerOnce() async {
    if (_registering) return false;
    _registering = true;
    try {
      final token = await FirebaseMessaging.instance.getToken();
      if (token == null) return false;
      await _api.registerDevice(token: token);
      final prefs = await SharedPreferences.getInstance();
      await prefs.setInt(_deviceIdKey, _api.deviceId!);
      await prefs.setString(_deviceSecretKey, _api.deviceSecret!);
      registered.value = true;
      return true;
    } catch (e) {
      debugPrint('Registrazione device fallita: $e');
      return false;
    } finally {
      _registering = false;
    }
  }

  Future<void> _onTokenRefresh(String token) async {
    try {
      if (_api.hasDevice) {
        await _api.updateDeviceToken(token);
      } else {
        await _registerOnce();
      }
    } catch (e) {
      debugPrint('Aggiornamento token fallito: $e');
    }
  }

  void _handleOpened(RemoteMessage message) {
    if (message.data.isEmpty) return;
    deepLink.value = AppDeepLink.fromData(message.data);
  }

  /// Consuma il deep-link corrente (la UI lo azzera dopo aver navigato).
  void clearDeepLink() => deepLink.value = null;

  void dispose() {
    registered.dispose();
    deepLink.dispose();
    foreground.dispose();
  }
}

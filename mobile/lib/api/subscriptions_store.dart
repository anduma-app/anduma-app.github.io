// Store osservabile delle sottoscrizioni alert dell'utente (M7).
// Sincronizzato col backend /me/subscriptions; richiede un device registrato
// (credenziali ApiClient valorizzate dal PushManager). Al primo alert creato
// chiede il permesso notifiche e registra il device; se non è possibile le
// operazioni restituiscono false e la UI lo segnala.
import 'package:flutter/foundation.dart';

import 'api_client.dart';
import 'models.dart';
import 'push_manager.dart';

class SubscriptionsStore extends ChangeNotifier {
  SubscriptionsStore(this._api, this._push);
  final ApiClient _api;
  final PushManager _push;

  List<Subscription> _subs = const [];
  bool _loaded = false;

  List<Subscription> get all => List.unmodifiable(_subs);
  bool get ready => _api.hasDevice;

  /// Le push sono possibili su questo device (Firebase configurato).
  bool get pushAvailable => _push.available;
  bool get loaded => _loaded;

  /// Attiva le push se serve e invia una notifica di prova. Ritorna il testo
  /// da mostrare all'utente.
  Future<String> sendTestPush() async {
    if (!await _push.enable()) {
      return 'Notifiche non attive: consentile nelle impostazioni del telefono o del browser.';
    }
    final error = await _api.testPush();
    return error == null
        ? 'Notifica inviata: dovrebbe arrivare entro pochi secondi.'
        : 'Notifica di prova non riuscita: $error';
  }

  /// Sottoscrizioni "imminent" attive per una fermata.
  List<Subscription> imminentForStop(String stopId) =>
      _subs.where((s) => s.kind == 'imminent' && s.stopId == stopId).toList();

  bool hasImminent(String stopId, String line) =>
      _subs.any((s) => s.kind == 'imminent' && s.stopId == stopId && s.line == line);

  Subscription? strikeForLine(String line) => _byKind('strike', line);
  Subscription? lineAlertForLine(String line) => _byKind('line_alert', line);

  Subscription? _byKind(String kind, String line) {
    for (final s in _subs) {
      if (s.kind == kind && s.line == line) return s;
    }
    return null;
  }

  /// Conta gli alert che toccano una fermata (per il badge sulla card).
  int countForStop(String stopId) => imminentForStop(stopId).length;

  Future<void> load() async {
    if (!ready) return;
    try {
      _subs = await _api.subscriptions();
      _loaded = true;
      notifyListeners();
    } catch (_) {
      // device non pronto / offline: si riprova al prossimo trigger
    }
  }

  /// Permesso notifiche concesso e device registrato. Il permesso si verifica a
  /// ogni nuovo alert: l'utente può averlo revocato dalle impostazioni.
  Future<bool> _ensureReady() async {
    if (!await _push.enable()) return false;
    if (!_loaded) await load();
    return ready;
  }

  Future<bool> addImminent(String stopId, String line, int thresholdMin) async {
    if (!await _ensureReady()) return false;
    try {
      final sub = await _api.addImminentAlert(
          stopId: stopId, line: line, thresholdMin: thresholdMin);
      _subs = [..._subs, sub];
      notifyListeners();
      return true;
    } catch (_) {
      return false;
    }
  }

  Future<bool> toggleStrike(String line, {required bool on}) =>
      _toggle('strike', line, on: on, create: () => _api.addStrikeAlert(line: line));

  Future<bool> toggleLineAlert(String line, {required bool on}) =>
      _toggle('line_alert', line, on: on, create: () => _api.addLineAlert(line: line));

  Future<bool> _toggle(
    String kind,
    String line, {
    required bool on,
    required Future<Subscription> Function() create,
  }) async {
    if (on ? !await _ensureReady() : !ready) return false;
    try {
      if (on) {
        _subs = [..._subs, await create()];
      } else {
        final existing = _byKind(kind, line);
        if (existing != null) {
          await _api.deleteSubscription(existing.id);
          _subs = _subs.where((s) => s.id != existing.id).toList();
        }
      }
      notifyListeners();
      return true;
    } catch (_) {
      return false;
    }
  }

  Future<bool> remove(int id) async {
    if (!ready) return false;
    try {
      await _api.deleteSubscription(id);
      _subs = _subs.where((s) => s.id != id).toList();
      notifyListeners();
      return true;
    } catch (_) {
      return false;
    }
  }
}

// Client REST verso il backend Transito Torino.
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import 'config.dart';
import 'models.dart';

class ApiException implements Exception {
  final String message;
  ApiException(this.message);
  @override
  String toString() => message;
}

class ApiClient {
  ApiClient({http.Client? client, String? base})
      : _client = client ?? http.Client(),
        _base = base ?? ApiConfig.apiBase;

  final http.Client _client;
  final String _base;

  /// Identità device anonima restituita da POST /v1/me/devices: id + segreto,
  /// inviati come header `X-Device-Id` / `X-Device-Secret` sulle chiamate `/me/*`.
  int? deviceId;
  String? deviceSecret;

  bool get hasDevice => deviceId != null && deviceSecret != null;

  Map<String, String> _headers({bool json = false}) => {
        if (json) 'Content-Type': 'application/json',
        if (hasDevice) 'X-Device-Id': '$deviceId',
        if (hasDevice) 'X-Device-Secret': deviceSecret!,
      };

  Uri _uri(String path, [Map<String, dynamic>? query]) {
    final q = (query ?? {})..removeWhere((_, v) => v == null);
    return Uri.parse('$_base/v1$path').replace(
      queryParameters: q.isEmpty ? null : q.map((k, v) => MapEntry(k, '$v')),
    );
  }

  Never _raise(int code) {
    if (code == 401) throw ApiException('Device non registrato');
    if (code == 404) throw ApiException('Non trovato');
    throw ApiException('Errore server ($code)');
  }

  Future<dynamic> _get(String path, [Map<String, dynamic>? query]) async {
    final http.Response res;
    try {
      res = await _client
          .get(_uri(path, query), headers: _headers())
          .timeout(const Duration(seconds: 12));
    } catch (e) {
      throw ApiException('Rete non raggiungibile');
    }
    if (res.statusCode >= 400) _raise(res.statusCode);
    return jsonDecode(utf8.decode(res.bodyBytes));
  }

  Future<dynamic> _send(String method, String path, Map<String, dynamic> body) async {
    final http.Response res;
    try {
      final req = http.Request(method, _uri(path))
        ..headers.addAll(_headers(json: true))
        ..body = jsonEncode(body);
      final streamed = await _client.send(req).timeout(const Duration(seconds: 12));
      res = await http.Response.fromStream(streamed);
    } catch (e) {
      throw ApiException('Rete non raggiungibile');
    }
    if (res.statusCode >= 400) _raise(res.statusCode);
    if (res.body.isEmpty) return null;
    return jsonDecode(utf8.decode(res.bodyBytes));
  }

  Future<void> _delete(String path) async {
    final http.Response res;
    try {
      res = await _client.delete(_uri(path), headers: _headers()).timeout(const Duration(seconds: 12));
    } catch (e) {
      throw ApiException('Rete non raggiungibile');
    }
    if (res.statusCode >= 400 && res.statusCode != 404) _raise(res.statusCode);
  }

  Future<List<TransitLine>> lines() async {
    final data = await _get('/lines') as List;
    return data.map((e) => TransitLine.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<List<Stop>> searchStops(String q, {int limit = 20}) async {
    if (q.trim().isEmpty) return const [];
    final data = await _get('/stops/search', {'q': q, 'limit': limit}) as List;
    return data.map((e) => Stop.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<ArrivalsResponse> arrivals(String stopId, {String? line}) async {
    final data = await _get('/stops/$stopId/arrivals', {'line': line}) as Map<String, dynamic>;
    return ArrivalsResponse.fromJson(data);
  }

  Future<VehiclesResponse> vehicles(String line) async {
    final data = await _get('/lines/$line/vehicles') as Map<String, dynamic>;
    return VehiclesResponse.fromJson(data);
  }

  Future<LineShape> lineShape(String line) async {
    final data = await _get('/lines/$line/shape') as Map<String, dynamic>;
    return LineShape.fromJson(data);
  }

  Future<AlertsResponse> alerts({String? line}) async {
    final data = await _get('/alerts', {'line': line}) as Map<String, dynamic>;
    return AlertsResponse.fromJson(data);
  }

  // --------------------------------------------------------------- /me (M7)

  /// Registra (o ri-registra) il device col token FCM e ne memorizza le credenziali.
  Future<void> registerDevice({required String token}) async {
    final platform = kIsWeb
        ? 'web'
        : defaultTargetPlatform == TargetPlatform.iOS
            ? 'ios'
            : 'android';
    final data = await _send('POST', '/me/devices', {'platform': platform, 'token': token})
        as Map<String, dynamic>;
    deviceId = (data['id'] as num).toInt();
    deviceSecret = data['secret'] as String;
  }

  /// Aggiorna il token FCM ruotato senza perdere preferiti e alert.
  Future<void> updateDeviceToken(String token) async {
    await _send('PUT', '/me/devices/token', {'token': token});
  }

  Future<List<Subscription>> subscriptions() async {
    final data = await _get('/me/subscriptions') as List;
    return data.map((e) => Subscription.fromJson(e as Map<String, dynamic>)).toList();
  }

  /// Crea un alert "imminent" (linea in arrivo entro [thresholdMin] alla fermata).
  Future<Subscription> addImminentAlert({
    required String stopId,
    required String line,
    required int thresholdMin,
  }) async {
    final data = await _send('POST', '/me/subscriptions', {
      'kind': 'imminent',
      'stop_id': stopId,
      'line': line,
      'threshold_min': thresholdMin,
    }) as Map<String, dynamic>;
    return Subscription.fromJson(data);
  }

  /// Crea un alert "strike" (sciopero) per una linea.
  Future<Subscription> addStrikeAlert({required String line}) async {
    final data = await _send('POST', '/me/subscriptions', {'kind': 'strike', 'line': line})
        as Map<String, dynamic>;
    return Subscription.fromJson(data);
  }

  /// Crea un alert "line_alert" (avvisi/deviazioni di servizio) per una linea.
  Future<Subscription> addLineAlert({required String line}) async {
    final data = await _send('POST', '/me/subscriptions', {'kind': 'line_alert', 'line': line})
        as Map<String, dynamic>;
    return Subscription.fromJson(data);
  }

  Future<void> deleteSubscription(int id) => _delete('/me/subscriptions/$id');

  /// Segnalazione o richiesta di funzionalità (anonima, senza device registrato).
  Future<void> sendFeedback({required String message, String? contact}) async {
    final platform = kIsWeb
        ? 'web'
        : defaultTargetPlatform == TargetPlatform.iOS
            ? 'ios'
            : 'android';
    await _send('POST', '/feedback', {
      'message': message,
      if (contact != null && contact.trim().isNotEmpty) 'contact': contact.trim(),
      'platform': platform,
    });
  }

  /// Notifica di prova al device corrente. Ritorna null se inviata, altrimenti
  /// il motivo del fallimento (testo del server, in italiano).
  Future<String?> testPush() async {
    final http.Response res;
    try {
      res = await _client
          .post(_uri('/me/test-push'), headers: _headers())
          .timeout(const Duration(seconds: 20));
    } catch (_) {
      return 'Rete non raggiungibile';
    }
    if (res.statusCode < 400) return null;
    try {
      final detail = (jsonDecode(utf8.decode(res.bodyBytes)) as Map)['detail'];
      if (detail is String) return detail;
    } catch (_) {}
    return 'Errore server (${res.statusCode})';
  }

  void close() => _client.close();
}

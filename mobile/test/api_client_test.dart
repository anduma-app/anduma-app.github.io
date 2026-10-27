// Contratto client ↔ backend senza rete: prefisso /v1, credenziali device, parsing.
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:transito/api/api_client.dart';

void main() {
  test(
    'registrazione device: /v1, credenziali salvate e inviate su /me',
    () async {
      final seen = <http.Request>[];
      final api = ApiClient(
        base: 'http://backend',
        client: MockClient((req) async {
          seen.add(req);
          if (req.url.path == '/v1/me/devices') {
            return http.Response(
              jsonEncode({
                'id': 7,
                'platform': 'android',
                'created_at': '2026-10-27T10:00:00Z',
                'secret': 's3cr3t',
              }),
              201,
            );
          }
          return http.Response('[]', 200);
        }),
      );

      await api.registerDevice(token: 'fcm-token');
      expect(api.hasDevice, isTrue);
      await api.subscriptions();

      expect(seen.first.url.toString(), 'http://backend/v1/me/devices');
      expect(seen.last.url.path, '/v1/me/subscriptions');
      expect(seen.last.headers['X-Device-Id'], '7');
      expect(seen.last.headers['X-Device-Secret'], 's3cr3t');
    },
  );

  test('avvisi: feed GTT non disponibile ma scioperi presenti', () async {
    final api = ApiClient(
      base: 'http://backend',
      client: MockClient((req) async {
        expect(req.url.path, '/v1/alerts');
        return http.Response(
          jsonEncode({
            'service_alerts': [],
            'service_alerts_available': false,
            'strikes': [
              {
                'start_date': '30/10/2026',
                'sector': 'Generale',
                'area': 'Italia',
              },
            ],
          }),
          200,
        );
      }),
    );
    final res = await api.alerts();
    expect(res.serviceAlertsAvailable, isFalse);
    expect(res.strikes.single.sector, 'Generale');
  });
}

// "Disattiva tutte": cancella ogni sottoscrizione e conta quelle non rimosse.
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:transito/api/api_client.dart';
import 'package:transito/api/push_manager.dart';
import 'package:transito/api/subscriptions_store.dart';

void main() {
  test('removeAll elimina tutte le notifiche e segnala i fallimenti', () async {
    final deleted = <String>[];
    final api =
        ApiClient(
            base: 'http://backend',
            client: MockClient((req) async {
              if (req.method == 'GET') {
                return http.Response(
                  jsonEncode([
                    for (final id in [1, 2, 3])
                      {'id': id, 'kind': 'imminent', 'stop_id': '252', 'line': '4', 'active': true},
                  ]),
                  200,
                );
              }
              deleted.add(req.url.path);
              // La 2 fallisce: deve restare nell'elenco.
              return http.Response('', req.url.path.endsWith('/2') ? 500 : 204);
            }),
          )
          ..deviceId = 1
          ..deviceSecret = 's';
    final store = SubscriptionsStore(api, PushManager(api));
    await store.load();
    expect(store.all, hasLength(3));

    expect(await store.removeAll(), 1);
    expect(deleted, ['/v1/me/subscriptions/1', '/v1/me/subscriptions/2', '/v1/me/subscriptions/3']);
    expect(store.all.map((s) => s.id), [2]);
  });
}

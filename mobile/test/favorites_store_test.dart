import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:transito/api/favorites_store.dart';

void main() {
  test('allLines unisce linee salvate e linee delle fermate salvate', () async {
    SharedPreferences.setMockInitialValues({
      'tt_favorites_v1': jsonEncode([
        {'type': 'line', 'ref': '4', 'name': 'Linea 4'},
        {'type': 'stop', 'ref': '252', 'name': 'Porta Nuova', 'lines': ['11', '12']},
        {'type': 'stop', 'ref': '350', 'name': 'Massari'}, // salvata prima delle linee
      ]),
    });
    final store = FavoritesStore();
    await store.load();
    expect(store.allLines, {'4', '11', '12'});

    await store.updateStopLines('350', ['55']);
    expect(store.allLines, {'4', '11', '12', '55'});
    final saved = (await SharedPreferences.getInstance()).getString('tt_favorites_v1')!;
    expect(saved, contains('"lines":["55"]'));
  });
}

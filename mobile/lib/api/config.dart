// Configurazione client API. Override a build-time con:
//   flutter run --dart-define=TT_API_BASE=http://192.168.1.10:8000    (device reale)
//   flutter build appbundle --dart-define=TT_API_BASE=https://api.example.org
import 'package:flutter/foundation.dart';

class ApiConfig {
  static const _defined = String.fromEnvironment('TT_API_BASE');

  /// True se l'URL del backend è stato passato a build-time (obbligatorio in release).
  static bool get isConfigured => _defined.isNotEmpty;

  /// Base URL REST del backend (senza `/v1`). In debug, senza override: emulatore
  /// Android → host della macchina (10.0.2.2), altrimenti localhost.
  static String get apiBase {
    if (isConfigured) return _defined;
    if (!kIsWeb && defaultTargetPlatform == TargetPlatform.android) {
      return 'http://10.0.2.2:8000';
    }
    return 'http://127.0.0.1:8000';
  }

  /// Base URL WebSocket, derivata da [apiBase] (http→ws, https→wss).
  static String get wsBase => apiBase.replaceFirst(RegExp(r'^http'), 'ws');
}

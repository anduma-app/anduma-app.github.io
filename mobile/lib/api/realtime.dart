// Streaming posizioni mezzi via WebSocket (WS /v1/ws/lines/{line}), con fallback.
import 'dart:async';
import 'dart:convert';

import 'package:web_socket_channel/web_socket_channel.dart';

import 'api_client.dart';
import 'config.dart';
import 'models.dart';

/// Stato della connessione realtime mostrato in UI (badge mappa).
enum RealtimeStatus { connecting, live, paused }

class VehiclesUpdate {
  final VehiclesResponse data;
  final RealtimeStatus status;
  const VehiclesUpdate(this.data, this.status);
}

/// Sottoscrive il WS della linea e ne emette gli aggiornamenti. Se il WS cade,
/// passa a `paused` e fa **fallback** al polling REST di `/v1/lines/{line}/vehicles`
/// (stesso payload), ritentando il WS con backoff: al primo frame ricevuto il
/// polling si ferma e lo stato torna `live`.
class VehiclesStream {
  VehiclesStream(this.line, {ApiClient? api}) : _api = api ?? ApiClient();

  final String line;
  final ApiClient _api;
  WebSocketChannel? _channel;
  StreamSubscription? _sub;
  Timer? _pollTimer;
  Timer? _reconnectTimer;
  int _failures = 0;
  bool _disposed = false;
  final _controller = StreamController<VehiclesUpdate>.broadcast();

  Stream<VehiclesUpdate> get stream => _controller.stream;

  void start() {
    _connectWs();
  }

  void _connectWs() {
    if (_disposed) return;
    try {
      final uri = Uri.parse('${ApiConfig.wsBase}/v1/ws/lines/$line');
      final channel = WebSocketChannel.connect(uri);
      _channel = channel;
      _sub = channel.stream.listen(
        (event) {
          try {
            final json = jsonDecode(event as String) as Map<String, dynamic>;
            _failures = 0;
            _pollTimer?.cancel();
            _pollTimer = null;
            _emit(VehiclesUpdate(VehiclesResponse.fromJson(json), RealtimeStatus.live));
          } catch (_) {/* frame malformato: ignora */}
        },
        onError: (_) => _onWsClosed(),
        onDone: _onWsClosed,
        cancelOnError: true,
      );
    } catch (_) {
      _onWsClosed();
    }
  }

  void _onWsClosed() {
    if (_disposed) return;
    _sub?.cancel();
    _sub = null;
    _channel = null;
    _fallbackToPolling();
    // Backoff 5s, 10s, 20s, … fino a 60s tra un tentativo WS e l'altro.
    final seconds = (5 * (1 << _failures.clamp(0, 4))).clamp(5, 60);
    _failures++;
    _reconnectTimer?.cancel();
    _reconnectTimer = Timer(Duration(seconds: seconds), _connectWs);
  }

  // Fallback: polling REST ogni 4s, segnalando lo stato come "in pausa" (non live).
  void _fallbackToPolling() {
    if (_pollTimer != null) return;
    _poll();
    _pollTimer = Timer.periodic(const Duration(seconds: 4), (_) => _poll());
  }

  Future<void> _poll() async {
    try {
      final data = await _api.vehicles(line);
      if (_pollTimer != null) _emit(VehiclesUpdate(data, RealtimeStatus.paused));
    } catch (_) {/* offline: mantieni l'ultimo stato noto */}
  }

  void _emit(VehiclesUpdate update) {
    if (!_disposed && !_controller.isClosed) _controller.add(update);
  }

  Future<void> dispose() async {
    _disposed = true;
    _pollTimer?.cancel();
    _reconnectTimer?.cancel();
    await _sub?.cancel();
    await _channel?.sink.close();
    await _controller.close();
    _api.close();
  }
}

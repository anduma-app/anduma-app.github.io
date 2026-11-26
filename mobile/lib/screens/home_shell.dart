// Shell di navigazione: bottom navigation a 4 voci + accesso a Informazioni.
// Orchestratore degli store condivisi (preferiti, sottoscrizioni, push) e del
// deep-link in arrivo dalle notifiche.
import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../api/favorites_store.dart';
import '../api/models.dart';
import '../api/push_manager.dart';
import '../api/subscriptions_store.dart';
import '../theme/tokens.dart';
import 'arrivi_screen.dart';
import 'avvisi_screen.dart';
import 'mappa_screen.dart';
import 'preferiti_screen.dart';

class HomeShell extends StatefulWidget {
  const HomeShell({super.key});

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  final _api = ApiClient();
  final _favs = FavoritesStore();
  late final _push = PushManager(_api);
  late final _subs = SubscriptionsStore(_api, _push);

  // Richiesta di aprire una fermata specifica negli Arrivi (deep-link push, mappa).
  final _arriviStopRequest = ValueNotifier<String?>(null);
  // Richiesta di mostrare gli avvisi di una linea (deep-link push).
  final _avvisiLineRequest = ValueNotifier<String?>(null);

  // Tab attiva e visibile (app in primo piano): i timer e gli stream di una
  // schermata girano solo mentre la sua tab è attiva.
  final _active = List.generate(4, (i) => ValueNotifier<bool>(i == 0));
  late final AppLifecycleListener _lifecycle;
  bool _foreground = true;

  // Tab già aperte almeno una volta: le altre non vengono costruite (la mappa
  // non apre WS né scarica tile finché l'utente non ci va).
  final _visited = <int>{0};

  int _index = 0;

  @override
  void initState() {
    super.initState();
    _lifecycle = AppLifecycleListener(onStateChange: (state) {
      _foreground = state == AppLifecycleState.resumed;
      _syncActive();
    });
    _favs.load();
    _seedLineModes();
    _initPush();
  }

  Future<void> _initPush() async {
    _push.registered.addListener(_subs.load); // registrazione anche in differita
    await _push.init();
    await _subs.load();
    _push.deepLink.addListener(_onDeepLink);
    _push.foreground.addListener(_onForegroundMessage);
    _onDeepLink(); // consuma un eventuale deep-link da app terminata
  }

  /// Carica l'elenco linee una volta per popolare il registry linea→modalità
  /// (icone tram/metro/bus reali da `route_type`). Best-effort.
  Future<void> _seedLineModes() async {
    try {
      final lines = await _api.lines();
      if (!mounted) return;
      LineModes.seed(lines);
      setState(() {});
    } catch (_) {
      // offline o backend giù: pill con euristica, nessun crash
    }
  }

  void _selectTab(int i) {
    setState(() {
      _index = i;
      _visited.add(i);
    });
    _syncActive();
  }

  void _syncActive() {
    for (var i = 0; i < _active.length; i++) {
      _active[i].value = _foreground && i == _index;
    }
  }

  /// Notifica sempre, anche se la richiesta coincide con la precedente.
  static void _request(ValueNotifier<String?> n, String? value) {
    n.value = null;
    n.value = value;
  }

  void _onDeepLink() {
    final link = _push.deepLink.value;
    if (link == null || !mounted) return;
    if (link.kind == 'imminent' && link.stopId != null) {
      _openStopInArrivi(link.stopId!);
    } else if (link.kind == 'strike' || link.kind == 'line_alert') {
      _request(_avvisiLineRequest, link.line?.isEmpty ?? true ? null : link.line);
      _selectTab(3);
    }
    _push.clearDeepLink();
  }

  void _openStopInArrivi(String stopId) {
    _request(_arriviStopRequest, stopId);
    _selectTab(0);
  }

  void _onForegroundMessage() {
    final m = _push.foreground.value;
    if (m == null || !mounted) return;
    final n = m.notification;
    final title = n?.title ?? m.data['kind'] ?? 'Avviso';
    final body = n?.body ?? '';
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(body.isEmpty ? title : '$title — $body'),
        action: m.data.isEmpty
            ? null
            : SnackBarAction(
                label: 'Apri',
                onPressed: () {
                  _push.deepLink.value = AppDeepLink.fromData(m.data);
                },
              ),
      ),
    );
  }

  @override
  void dispose() {
    _push.deepLink.removeListener(_onDeepLink);
    _push.foreground.removeListener(_onForegroundMessage);
    _push.registered.removeListener(_subs.load);
    _lifecycle.dispose();
    for (final a in _active) {
      a.dispose();
    }
    _arriviStopRequest.dispose();
    _avvisiLineRequest.dispose();
    _push.dispose();
    _api.close();
    _favs.dispose();
    _subs.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = TTColors.of(context);
    final pages = <Widget Function()>[
      () => ArriviScreen(
          api: _api,
          favs: _favs,
          subs: _subs,
          active: _active[0],
          openStop: _arriviStopRequest),
      () => MappaScreen(
          api: _api, favs: _favs, active: _active[1], onOpenStop: _openStopInArrivi),
      () => PreferitiScreen(api: _api, favs: _favs, subs: _subs, active: _active[2]),
      () => AvvisiScreen(
          api: _api, favs: _favs, active: _active[3], openLine: _avvisiLineRequest),
    ];

    return Scaffold(
      backgroundColor: c.bg,
      body: IndexedStack(
        index: _index,
        children: [
          for (var i = 0; i < pages.length; i++)
            _visited.contains(i) ? pages[i]() : const SizedBox.shrink(),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: _selectTab,
        backgroundColor: c.surface,
        indicatorColor: c.primarySoft,
        destinations: const [
          NavigationDestination(
              icon: Icon(Icons.access_time), selectedIcon: Icon(Icons.access_time_filled), label: 'Arrivi'),
          NavigationDestination(icon: Icon(Icons.map_outlined), selectedIcon: Icon(Icons.map), label: 'Mappa'),
          NavigationDestination(
              icon: Icon(Icons.star_border), selectedIcon: Icon(Icons.star), label: 'Preferiti'),
          NavigationDestination(
              icon: Icon(Icons.campaign_outlined), selectedIcon: Icon(Icons.campaign), label: 'Avvisi'),
        ],
      ),
    );
  }
}

// Schermata Preferiti: fermate e linee salvate, arrivi inline auto-refresh.
import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../api/favorites_store.dart';
import '../api/models.dart';
import '../api/subscriptions_store.dart';
import '../theme/tokens.dart';
import '../widgets/alert_sheet.dart';
import '../widgets/arrival_row.dart';
import '../widgets/info_button.dart';
import '../widgets/line_pill.dart';
import '../widgets/state_views.dart';

class PreferitiScreen extends StatefulWidget {
  const PreferitiScreen(
      {super.key,
      required this.api,
      required this.favs,
      required this.subs,
      required this.active,
      this.onShowOnMap});
  final ApiClient api;
  final FavoritesStore favs;
  final SubscriptionsStore subs;

  /// True mentre la tab è visibile e l'app in primo piano (refresh attivo).
  final ValueListenable<bool> active;

  /// Mostra una fermata sulla mappa (cambio tab gestito dalla shell).
  final void Function(Stop stop)? onShowOnMap;

  @override
  State<PreferitiScreen> createState() => _PreferitiScreenState();
}

class _PreferitiScreenState extends State<PreferitiScreen> {
  Timer? _refresh;
  // Funzioni di ricarica delle card fermata montate (refresh periodico e pull).
  final _loaders = <Future<void> Function()>{};

  @override
  void initState() {
    super.initState();
    widget.active.addListener(_onActiveChanged);
    _onActiveChanged();
  }

  void _onActiveChanged() {
    _refresh?.cancel();
    if (!widget.active.value) return;
    _reloadAll(); // dati freschi tornando sulla tab
    _refresh = Timer.periodic(const Duration(seconds: 30), (_) => _reloadAll());
  }

  Future<void> _reloadAll() => Future.wait([for (final load in _loaders) load()]);

  @override
  void dispose() {
    widget.active.removeListener(_onActiveChanged);
    _refresh?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = TTColors.of(context);
    return SafeArea(
      bottom: false,
      child: ListenableBuilder(
        listenable: widget.favs,
        builder: (context, _) {
          final stops = widget.favs.stops;
          final lines = widget.favs.lines;
          final empty = stops.isEmpty && lines.isEmpty;
          return Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _title(c),
              _activeAlertsBar(c),
              Expanded(
                child: empty
                    ? const StateView(
                        icon: Icons.star_border,
                        title: 'Ancora nessun preferito',
                        body:
                            'Cerca una fermata o apri la mappa e tocca la stella per salvarla qui.',
                      )
                    : RefreshIndicator(
                        onRefresh: _reloadAll,
                        child: ListView(
                          padding:
                              const EdgeInsets.fromLTRB(TTSpace.x4, 0, TTSpace.x4, TTSpace.x8),
                          children: [
                            if (stops.isNotEmpty) ...[
                              _sectionLabel(c, 'FERMATE'),
                              const SizedBox(height: TTSpace.x2),
                              for (final f in stops)
                                _StopCard(
                                  key: ValueKey(f.ref),
                                  fav: f,
                                  api: widget.api,
                                  favs: widget.favs,
                                  subs: widget.subs,
                                  loaders: _loaders,
                                  onShowOnMap: widget.onShowOnMap,
                                ),
                            ],
                            if (lines.isNotEmpty) ...[
                              SizedBox(height: stops.isNotEmpty ? TTSpace.x5 : 0),
                              _sectionLabel(c, 'LINEE'),
                              const SizedBox(height: TTSpace.x2),
                              for (final f in lines) _LineCard(fav: f, favs: widget.favs, subs: widget.subs),
                            ],
                          ],
                        ),
                      ),
              ),
            ],
          );
        },
      ),
    );
  }

  Widget _title(TTColors c) => Padding(
        padding: const EdgeInsets.fromLTRB(TTSpace.x5, TTSpace.x2, TTSpace.x5, TTSpace.x3),
        child: Row(
          children: [
            Text(
              'Preferiti',
              style: TextStyle(
                  fontSize: 28, fontWeight: FontWeight.w800, letterSpacing: -0.6, color: c.ink),
            ),
            const Spacer(),
            const InfoButton(),
          ],
        ),
      );

  /// Striscia sotto il titolo, visibile solo con notifiche attive: le spegne tutte.
  Widget _activeAlertsBar(TTColors c) => ListenableBuilder(
        listenable: widget.subs,
        builder: (context, _) {
          final n = widget.subs.all.length;
          if (n == 0) return const SizedBox.shrink();
          return Padding(
            padding: const EdgeInsets.fromLTRB(TTSpace.x4, 0, TTSpace.x4, TTSpace.x3),
            child: Container(
              padding: const EdgeInsets.fromLTRB(TTSpace.x4, TTSpace.x1, TTSpace.x1, TTSpace.x1),
              decoration: BoxDecoration(
                color: c.surface,
                border: Border.all(color: c.border),
                borderRadius: BorderRadius.circular(TTRadius.lg),
              ),
              child: Row(
                children: [
                  Icon(Icons.notifications_active, size: 18, color: c.accent),
                  const SizedBox(width: TTSpace.x2),
                  Expanded(
                    child: Text(n == 1 ? '1 notifica attiva' : '$n notifiche attive',
                        style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: c.ink)),
                  ),
                  TextButton.icon(
                    onPressed: () => _confirmRemoveAll(n),
                    icon: const Icon(Icons.notifications_off_outlined, size: 18),
                    label: const Text('Disattiva tutte'),
                  ),
                ],
              ),
            ),
          );
        },
      );

  Future<void> _confirmRemoveAll(int n) async {
    final messenger = ScaffoldMessenger.of(context);
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Disattivare tutte le notifiche?'),
        content: Text(n == 1
            ? 'Verrà disattivata la notifica attiva. Potrai riattivarla con la campanella.'
            : 'Verranno disattivate tutte le $n notifiche attive. Potrai riattivarle con la '
                'campanella.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Annulla')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Disattiva')),
        ],
      ),
    );
    if (ok != true) return;
    final failed = await widget.subs.removeAll();
    messenger.showSnackBar(SnackBar(
        content: Text(failed == 0
            ? 'Notifiche disattivate.'
            : 'Non è stato possibile disattivarne $failed: controlla la connessione e riprova.')));
  }

  Widget _sectionLabel(TTColors c, String label) => Text(
        label,
        style: TextStyle(
            fontSize: 11, fontWeight: FontWeight.w700, color: c.inkMuted, letterSpacing: 1.2),
      );
}

// ---------------------------------------------------------------- card fermata
class _StopCard extends StatefulWidget {
  const _StopCard({
    super.key,
    required this.fav,
    required this.api,
    required this.favs,
    required this.subs,
    required this.loaders,
    this.onShowOnMap,
  });
  final void Function(Stop stop)? onShowOnMap;
  final LocalFavorite fav;
  final ApiClient api;
  final FavoritesStore favs;
  final SubscriptionsStore subs;
  final Set<Future<void> Function()> loaders;

  @override
  State<_StopCard> createState() => _StopCardState();
}

class _StopCardState extends State<_StopCard> {
  ArrivalsResponse? _data;
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    widget.loaders.add(_load);
    _load();
  }

  @override
  void dispose() {
    widget.loaders.remove(_load);
    super.dispose();
  }

  Future<void> _load() async {
    setState(() => _loading = _data == null);
    try {
      final res = await widget.api.arrivals(widget.fav.ref);
      if (mounted) setState(() { _data = res; _error = null; _loading = false; });
    } catch (e) {
      if (mounted) setState(() { _error = '$e'; _loading = false; });
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = TTColors.of(context);
    return Dismissible(
      key: ValueKey('stop_${widget.fav.ref}'),
      direction: DismissDirection.endToStart,
      background: _dismissBg(c),
      onDismissed: (_) => widget.favs.remove(widget.fav.type, widget.fav.ref),
      child: Container(
        margin: const EdgeInsets.only(bottom: TTSpace.x3),
        decoration: BoxDecoration(
          color: c.surface,
          border: Border.all(color: c.border),
          borderRadius: BorderRadius.circular(TTRadius.lg),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _header(c),
            _body(c),
          ],
        ),
      ),
    );
  }

  Widget _header(TTColors c) => Padding(
        padding: const EdgeInsets.fromLTRB(TTSpace.x4, TTSpace.x3, TTSpace.x2, 0),
        child: Row(
          children: [
            Icon(Icons.place_outlined, size: 14, color: c.primary),
            const SizedBox(width: 6),
            Expanded(
              child: Text(
                widget.fav.name,
                style:
                    TextStyle(fontSize: 16, fontWeight: FontWeight.w800, color: c.ink),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
              ),
            ),
            IconButton(
              icon: Icon(Icons.map_outlined, size: 20, color: c.inkMuted),
              tooltip: 'Mostra sulla mappa',
              onPressed: () => widget.onShowOnMap
                  ?.call(Stop(stopId: widget.fav.ref, name: widget.fav.name)),
            ),
            ListenableBuilder(
              listenable: widget.subs,
              builder: (context, _) {
                final n = widget.subs.countForStop(widget.fav.ref);
                return IconButton(
                  icon: Icon(n > 0 ? Icons.notifications_active : Icons.notifications_none,
                      size: 20, color: n > 0 ? c.accent : c.inkMuted),
                  tooltip: 'Avvisami all\'arrivo',
                  onPressed: _openAlerts,
                );
              },
            ),
            IconButton(
              icon: Icon(Icons.star, size: 20, color: c.accent),
              tooltip: 'Rimuovi dai preferiti',
              onPressed: () => widget.favs.remove(widget.fav.type, widget.fav.ref),
            ),
          ],
        ),
      );

  void _openAlerts() {
    final lines = <String>{for (final a in _data?.arrivals ?? const []) if (a.line != null) a.line!}
        .toList()
      ..sort();
    showStopAlertSheet(
      context,
      stopId: widget.fav.ref,
      stopName: widget.fav.name,
      lines: lines,
      subs: widget.subs,
    );
  }

  Widget _body(TTColors c) {
    if (_loading) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: TTSpace.x4),
        child: ArrivalRowSkeleton(),
      );
    }
    if (_error != null) {
      return Padding(
        padding: const EdgeInsets.fromLTRB(TTSpace.x4, TTSpace.x2, TTSpace.x4, TTSpace.x3),
        child: Text('Impossibile aggiornare',
            style: TextStyle(fontSize: 13, color: c.inkMuted)),
      );
    }
    final arrivals = _data?.arrivals.take(3).toList() ?? const [];
    if (arrivals.isEmpty) {
      return Padding(
        padding: const EdgeInsets.fromLTRB(TTSpace.x4, TTSpace.x2, TTSpace.x4, TTSpace.x3),
        child: Text('Nessun passaggio previsto',
            style: TextStyle(fontSize: 13, color: c.inkMuted)),
      );
    }
    return ClipRRect(
      borderRadius: const BorderRadius.vertical(bottom: Radius.circular(TTRadius.lg)),
      child: Column(children: arrivals.map((a) => ArrivalRow(arrival: a)).toList()),
    );
  }
}

// ----------------------------------------------------------------- card linea
class _LineCard extends StatelessWidget {
  const _LineCard({required this.fav, required this.favs, required this.subs});
  final LocalFavorite fav;
  final FavoritesStore favs;
  final SubscriptionsStore subs;

  @override
  Widget build(BuildContext context) {
    final c = TTColors.of(context);
    return Dismissible(
      key: ValueKey('line_${fav.ref}'),
      direction: DismissDirection.endToStart,
      background: _dismissBg(c),
      onDismissed: (_) => favs.remove(fav.type, fav.ref),
      child: Container(
        margin: const EdgeInsets.only(bottom: TTSpace.x3),
        padding: const EdgeInsets.fromLTRB(TTSpace.x4, TTSpace.x3, TTSpace.x2, TTSpace.x3),
        decoration: BoxDecoration(
          color: c.surface,
          border: Border.all(color: c.border),
          borderRadius: BorderRadius.circular(TTRadius.lg),
        ),
        child: Row(
          children: [
            LinePill(number: fav.ref, mode: modeForLine(fav.ref), size: PillSize.lg),
            const SizedBox(width: TTSpace.x3),
            Expanded(
              child: Text(
                fav.name,
                style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: c.ink),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
              ),
            ),
            ListenableBuilder(
              listenable: subs,
              builder: (context, _) {
                final on = subs.strikeForLine(fav.ref) != null ||
                    subs.lineAlertForLine(fav.ref) != null;
                return IconButton(
                  icon: Icon(on ? Icons.notifications_active : Icons.notifications_none,
                      size: 20, color: on ? c.accent : c.inkMuted),
                  tooltip: 'Avvisi e scioperi',
                  onPressed: () => showLineAlertSheet(context, line: fav.ref, subs: subs),
                );
              },
            ),
            IconButton(
              icon: Icon(Icons.star, size: 20, color: c.accent),
              tooltip: 'Rimuovi dai preferiti',
              onPressed: () => favs.remove(fav.type, fav.ref),
            ),
          ],
        ),
      ),
    );
  }
}

Widget _dismissBg(TTColors c) => Container(
      alignment: Alignment.centerRight,
      padding: const EdgeInsets.only(right: TTSpace.x4),
      decoration: BoxDecoration(
        color: TTStatus.strike.base,
        borderRadius: BorderRadius.circular(TTRadius.lg),
      ),
      child: const Icon(Icons.delete_outline, color: Colors.white),
    );

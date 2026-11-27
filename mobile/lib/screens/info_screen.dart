// Schermata Informazioni: come funziona l'app, feedback, fonti dati (crediti obbligatori).
import 'package:flutter/material.dart';

import '../theme/tokens.dart';
import '../widgets/feedback_sheet.dart';

class InfoScreen extends StatelessWidget {
  const InfoScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final c = TTColors.of(context);

    Widget sectionLabel(String s) => Padding(
          padding: const EdgeInsets.only(bottom: TTSpace.x3),
          child: Text(s,
              style: TextStyle(
                  fontSize: 11, fontWeight: FontWeight.w700, color: c.inkMuted, letterSpacing: 1.2)),
        );

    Widget credit(IconData icon, String title, String body) => Container(
          margin: const EdgeInsets.only(bottom: TTSpace.x3),
          padding: const EdgeInsets.all(TTSpace.x4),
          decoration: BoxDecoration(
            color: c.surface,
            border: Border.all(color: c.border),
            borderRadius: BorderRadius.circular(TTRadius.lg),
          ),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(icon, size: 18, color: c.primary),
              const SizedBox(width: TTSpace.x3),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(title,
                        style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700, color: c.ink)),
                    const SizedBox(height: 4),
                    Text(body, style: TextStyle(fontSize: 13, color: c.inkMuted, height: 1.45)),
                  ],
                ),
              ),
            ],
          ),
        );

    return SafeArea(
      child: ListView(
        padding: const EdgeInsets.all(TTSpace.x5),
        children: [
          _appHeader(c),
          const SizedBox(height: TTSpace.x5),
          Text(
            'Anduma, in piemontese «andiamo»: ti dice quando passa il prossimo bus, tram o '
            'metro a Torino, così sai quando è ora di andare. Usa i dati aperti ufficiali della '
            'Città di Torino, di GTT e di 5T, che il nostro server aggiorna in continuazione. I '
            'tempi di arrivo sono stime di 5T (Muoversi a Torino) e possono differire da quelli '
            'reali.',
            style: TextStyle(fontSize: 14, color: c.ink, height: 1.5),
          ),
          const SizedBox(height: TTSpace.x6),
          sectionLabel('COSA PUOI FARE'),
          credit(Icons.schedule, 'Arrivi',
              'Cerca una fermata per nome o numero di palina e guarda i prossimi passaggi '
                  'in tempo reale.'),
          credit(Icons.map_outlined, 'Mappa',
              'Scegli una linea e segui i mezzi lungo il percorso.'),
          credit(Icons.star_border, 'Preferiti',
              'Salva fermate e linee con la stella per ritrovarle subito.'),
          credit(Icons.notifications_none, 'Notifiche',
              'Tocca la campanella su una fermata per essere avvisato quando la tua linea sta '
                  'arrivando, oppure su una linea preferita per scioperi e deviazioni. Per '
                  'spegnerle tutte: Preferiti → Disattiva tutte.'),
          credit(Icons.campaign_outlined, 'Avvisi',
              'Deviazioni e scioperi in corso, filtrabili per linee preferite, solo scioperi '
                  'o singola linea.'),
          const SizedBox(height: TTSpace.x5),
          sectionLabel('FEEDBACK'),
          Text(
            'Hai trovato un problema o ti manca qualcosa? Scrivici: valgono anche le richieste '
            'di nuove funzionalità.',
            style: TextStyle(fontSize: 13, color: c.inkMuted, height: 1.45),
          ),
          const SizedBox(height: TTSpace.x3),
          FilledButton.icon(
            onPressed: () => showFeedbackSheet(context),
            icon: const Icon(Icons.chat_bubble_outline),
            label: const Text('Invia un feedback'),
          ),
          const SizedBox(height: TTSpace.x6),
          sectionLabel('FONTI DATI'),
          credit(Icons.directions_transit, 'Trasporto pubblico',
              'Città di Torino / GTT — licenza CC BY 4.0'),
          credit(Icons.schedule, 'Arrivi in tempo reale', '5T / Muoversi a Torino'),
          credit(Icons.warning_amber_rounded, 'Scioperi',
              'MIT — Osservatorio sui Conflitti Sindacali'),
          credit(Icons.map_outlined, 'Mappa', '© OpenStreetMap contributors'),
          const SizedBox(height: TTSpace.x5),
          _footer(c),
        ],
      ),
    );
  }

  Widget _appHeader(TTColors c) => Row(
        children: [
          Container(
            width: 52,
            height: 52,
            decoration: BoxDecoration(
              color: c.primary,
              borderRadius: BorderRadius.circular(TTRadius.lg),
            ),
            child: Icon(Icons.directions_transit, color: c.accent, size: 28),
          ),
          const SizedBox(width: TTSpace.x4),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Anduma',
                    style: TextStyle(
                        fontSize: 22, fontWeight: FontWeight.w800, letterSpacing: -0.4, color: c.ink)),
                const SizedBox(height: 2),
                Text('Sai quando passa, sai quando andare · v0.1',
                    style: TextStyle(fontSize: 13, color: c.inkMuted)),
              ],
            ),
          ),
        ],
      );

  Widget _footer(TTColors c) => Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(Icons.auto_awesome, size: 14, color: c.inkSubtle),
          const SizedBox(width: 6),
          Text('Sviluppato con Claude Code',
              style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: c.inkSubtle)),
        ],
      );
}

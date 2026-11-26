// Modulo di feedback: segnalazioni e richieste di nuove funzionalità.
// Il messaggio arriva al backend (tabella `feedback`), senza account.
import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../theme/tokens.dart';

Future<void> showFeedbackSheet(BuildContext context) {
  final c = TTColors.of(context);
  return showModalBottomSheet(
    context: context,
    backgroundColor: c.surface,
    isScrollControlled: true,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(TTRadius.x2l)),
    ),
    builder: (_) => const _FeedbackSheet(),
  );
}

class _FeedbackSheet extends StatefulWidget {
  const _FeedbackSheet();

  @override
  State<_FeedbackSheet> createState() => _FeedbackSheetState();
}

class _FeedbackSheetState extends State<_FeedbackSheet> {
  final _message = TextEditingController();
  final _contact = TextEditingController();
  bool _sending = false;

  @override
  void initState() {
    super.initState();
    _message.addListener(() => setState(() {}));
  }

  @override
  void dispose() {
    _message.dispose();
    _contact.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final messenger = ScaffoldMessenger.of(context);
    final navigator = Navigator.of(context);
    setState(() => _sending = true);
    final api = ApiClient();
    try {
      await api.sendFeedback(message: _message.text.trim(), contact: _contact.text);
      navigator.pop();
      messenger.showSnackBar(const SnackBar(content: Text('Grazie! Feedback inviato.')));
    } catch (_) {
      if (mounted) setState(() => _sending = false);
      messenger.showSnackBar(
          const SnackBar(content: Text('Invio non riuscito: controlla la connessione e riprova.')));
    } finally {
      api.close();
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = TTColors.of(context);
    final canSend = !_sending && _message.text.trim().length >= 3;
    return Padding(
      padding: EdgeInsets.fromLTRB(
          TTSpace.x5, TTSpace.x5, TTSpace.x5, TTSpace.x5 + MediaQuery.viewInsetsOf(context).bottom),
      child: SafeArea(
        top: false,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('Invia un feedback',
                style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800, color: c.ink)),
            const SizedBox(height: 6),
            Text(
              'Segnala un problema, un dato sbagliato o proponi una nuova funzionalità: '
              'ogni richiesta è benvenuta.',
              style: TextStyle(fontSize: 13, color: c.inkMuted, height: 1.4),
            ),
            const SizedBox(height: TTSpace.x4),
            TextField(
              controller: _message,
              autofocus: true,
              minLines: 4,
              maxLines: 8,
              maxLength: 2000,
              textCapitalization: TextCapitalization.sentences,
              decoration: const InputDecoration(
                hintText: 'Scrivi qui il tuo messaggio…',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: TTSpace.x2),
            TextField(
              controller: _contact,
              maxLength: 200,
              keyboardType: TextInputType.emailAddress,
              decoration: const InputDecoration(
                labelText: 'Email (facoltativa, se vuoi una risposta)',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: TTSpace.x3),
            FilledButton.icon(
              onPressed: canSend ? _send : null,
              icon: _sending
                  ? const SizedBox(
                      width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                  : const Icon(Icons.send),
              label: const Text('Invia'),
            ),
          ],
        ),
      ),
    );
  }
}

// Accesso alla schermata Informazioni/Fonti (crediti dati obbligatori, CC BY 4.0).
import 'package:flutter/material.dart';

import '../screens/info_screen.dart';
import '../theme/tokens.dart';

class InfoButton extends StatelessWidget {
  const InfoButton({super.key});

  @override
  Widget build(BuildContext context) {
    final c = TTColors.of(context);
    return IconButton(
      tooltip: 'Informazioni e fonti dati',
      icon: Icon(Icons.info_outline, color: c.inkMuted),
      onPressed: () => Navigator.of(context).push(
        MaterialPageRoute(
          builder: (_) => Scaffold(
            backgroundColor: c.bg,
            appBar: AppBar(title: const Text('Informazioni')),
            body: const InfoScreen(),
          ),
        ),
      ),
    );
  }
}

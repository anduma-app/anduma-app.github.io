// Transito Torino — client Flutter (M7: arrivi, mappa, preferiti, avvisi, push).
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'api/config.dart';
import 'screens/home_shell.dart';
import 'theme/app_theme.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  if (kReleaseMode && !ApiConfig.isConfigured) {
    // Una release senza backend punterebbe al telefono stesso: meglio fallire subito.
    throw StateError('Build release senza --dart-define=TT_API_BASE=https://...');
  }
  LicenseRegistry.addLicense(() async* {
    final ofl = await rootBundle.loadString('assets/fonts/OFL.txt');
    yield LicenseEntryWithLineBreaks(const ['Manrope'], ofl);
  });
  runApp(const TransitoApp());
}

class TransitoApp extends StatelessWidget {
  const TransitoApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Transito Torino',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.light(),
      darkTheme: AppTheme.dark(),
      themeMode: ThemeMode.system, // light-default, dark se di sistema
      home: const HomeShell(),
    );
  }
}

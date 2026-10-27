package it.anduma.transito

import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Build
import android.os.Bundle
import io.flutter.embedding.android.FlutterActivity

class MainActivity : FlutterActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        createAlertsChannel()
    }

    // Canale ad alta importanza: le push compaiono come banner anche ad app chiusa.
    // Il backend invia su questo id (vedi backend/app/push.py); è anche il default
    // FCM nel manifest. Idempotente: Android ignora la ricreazione.
    private fun createAlertsChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val channel = NotificationChannel(
            ALERTS_CHANNEL_ID,
            "Alert passaggi e scioperi",
            NotificationManager.IMPORTANCE_HIGH,
        ).apply {
            description = "Mezzo in arrivo alla fermata, scioperi e avvisi sulle tue linee"
        }
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    companion object {
        const val ALERTS_CHANNEL_ID = "transito_alerts"
    }
}

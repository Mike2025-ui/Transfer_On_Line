package com.example.gateway_apk

import android.content.Context
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.Worker
import androidx.work.WorkerParameters
import java.util.concurrent.TimeUnit

/**
 * Self-healing check: WorkManager guarantees this runs roughly every 15
 * minutes (its documented minimum periodic interval) even if the process
 * hosting [GatewayForegroundService] has died, restarting it if it should
 * be running but hasn't reported alive recently. Deliberately plain Kotlin,
 * no Flutter engine involved - creating one just to read a single
 * timestamp would be slow and wasteful for a check this simple.
 *
 * Stabilisation RC1 (priorité moyenne n°10) : [STALE_THRESHOLD_MS] était à 5
 * minutes, un chiffre explicitement provisoire dans une version antérieure
 * de ce commentaire. Le recalibrer par rapport à ce que cette classe peut
 * réellement observer : elle ne s'exécute jamais plus souvent que
 * `PeriodicWorkRequestBuilder`'s 15 minutes (et souvent plus rarement -
 * Doze/App Standby retardent fréquemment le travail périodique au-delà du
 * minimum documenté). Un seuil de 5 minutes n'achetait aucune détection
 * plus fine que 15 minutes ne le permet déjà - la latence réelle de
 * détection est bornée par le rythme des vérifications, pas par le seuil -
 * et laissait trop peu de marge face à un ralentissement transitoire non
 * fatal du tick Dart (Doze bref, pression CPU) qui aurait pu déclencher un
 * redémarrage inutile d'un service en réalité toujours vivant. 10 minutes
 * reste confortablement sous les 15 minutes garanties : un service
 * réellement mort est encore certain d'être détecté dès la prochaine
 * exécution planifiée (son inactivité aura alors dépassé les 15 minutes
 * complètes), tout en doublant la tolérance aux ralentissements transitoires
 * avant conclusion erronée. Reste néanmoins une valeur raisonnée, pas
 * validée sur téléphone réel - voir la tâche de validation terrain, hors
 * périmètre de cet environnement.
 */
class GatewayWatchdogWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result {
        val prefs = GatewayForegroundService.watchdogPrefs(applicationContext)
        val desired = prefs.getBoolean(GatewayForegroundService.KEY_DESIRED_STATE, true)
        if (!desired) return Result.success() // the user deliberately stopped it - never override that

        val lastAliveAt = prefs.getLong(GatewayForegroundService.KEY_LAST_ALIVE_AT, 0L)
        val staleSince = System.currentTimeMillis() - lastAliveAt
        if (lastAliveAt == 0L || staleSince > STALE_THRESHOLD_MS) {
            GatewayForegroundService.start(applicationContext)
        }
        return Result.success()
    }

    companion object {
        private const val STALE_THRESHOLD_MS = 10 * 60 * 1000L
        private const val WORK_NAME = "gateway_watchdog"

        /** Idempotent - safe to call on every app launch (see MainActivity.onCreate). */
        fun enqueue(context: Context) {
            val request = PeriodicWorkRequestBuilder<GatewayWatchdogWorker>(15, TimeUnit.MINUTES).build()
            WorkManager.getInstance(context).enqueueUniquePeriodicWork(
                WORK_NAME,
                ExistingPeriodicWorkPolicy.KEEP,
                request,
            )
        }
    }
}

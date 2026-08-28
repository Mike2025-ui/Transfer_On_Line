package com.example.gateway_apk

import android.accessibilityservice.AccessibilityService
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.text.TextUtils
import android.util.Log
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo

/**
 * Étapes de la machine d'état (Phase D3). [WAITING_FOR_NEXT_SCREEN] revient
 * vers [READING_SCREEN] tant qu'un nouveau champ de saisie est détecté.
 * L'émission de [UssdStepEvent.FinalField] fait transiter directement vers
 * [WAITING_FOR_RESULT] - mais la classification SUCCESS/FAILED n'y est
 * jamais produite avant que le Backend n'ait confirmé via
 * [UssdAccessibilityService.onBackendDone] (voir [backendConfirmedDone]).
 * Boucle non bornée à une itération (voir [UssdAccessibilityService.MAX_ITERATIONS]
 * pour le seul plafond, un garde-fou de sécurité, pas une limitation métier).
 */
enum class UssdSessionState {
    IDLE,
    STARTING,
    WAITING_FOR_USSD,
    READING_SCREEN,
    WAITING_FOR_INPUT,
    ENTERING_VALUES,
    SUBMITTING,
    WAITING_FOR_NEXT_SCREEN,
    WAITING_FOR_RESULT,
    FINISHED,
    FAILED,
    TIMEOUT,
}

/** Timeouts par étape - aucun ne doit permettre à une session de rester
 * bloquée indéfiniment (voir aussi [UssdAccessibilityService.MAX_ITERATIONS]
 * et le timeout global de session). Constantes nommées, pas de valeur
 * magique inline. Phase D3 : les 5 constantes historiques ne sont pas
 * modifiées ; [SCREEN_STABILIZATION_MS] et [RESULT_TIMEOUT_MS] sont les
 * deux seuls ajouts. */
object UssdTimeouts {
    const val WAITING_FOR_USSD_MS = 15_000L
    const val WAITING_FOR_INPUT_MS = 10_000L
    const val SUBMITTING_MS = 10_000L
    const val WAITING_FOR_NEXT_SCREEN_MS = 20_000L
    const val SESSION_MAX_MS = 90_000L

    /** Phase D3 : délai de confirmation avant de traiter un écran sans
     * champ comme FINAL_FIELD, et avant de classifier un écran de résultat
     * - évite le faux positif déjà observé (panneau système pris pour un
     * écran USSD, Phase 8.2). Réutilisée pour les deux cas (point 19) -
     * aucune constante supplémentaire créée. Valeur initiale raisonnable,
     * à recalibrer après test réel. */
    const val SCREEN_STABILIZATION_MS = 400L

    /** Phase D3 : timeout dédié à WAITING_FOR_RESULT, plus fin que de
     * compter uniquement sur SESSION_MAX_MS pour cette étape précise. */
    const val RESULT_TIMEOUT_MS = 20_000L
}

/**
 * Paramètres d'armement d'une session (Phase D3). Volontairement dépourvu
 * de toute donnée métier (numéro Gateway, UUID Gateway, numéro client,
 * montant, PIN) - le Backend/D4 les connaît, ce service ne les stocke
 * jamais. [simSlot] n'est ici qu'une information transportée jusqu'aux
 * logs, jamais utilisée pour sélectionner quoi que ce soit ici (voir
 * [SimResolver], non modifié).
 */
data class UssdSessionConfig(
    val simSlot: Int?,
)

/**
 * Événements produits par le service à destination de D4 (Phase D3) - pure
 * signalisation locale, aucun appel HTTP, aucune connaissance du Backend ici.
 */
sealed class UssdStepEvent {
    data class NewField(val fieldCount: Int) : UssdStepEvent()
    object FinalField : UssdStepEvent()
    data class Result(val status: String, val operatorMessage: String) : UssdStepEvent()
    data class Failed(val errorCode: String, val detail: String) : UssdStepEvent()
    object Timeout : UssdStepEvent()
}

/** Pure, sans dépendance Android (Phase D3, correction stabilisation) :
 * décide l'événement à produire une fois - et seulement une fois - qu'un
 * écran a été confirmé stable. Au moins un champ -> NewField(fieldCount),
 * aucun champ -> FinalField. Testable en JUnit sans simuler
 * AccessibilityNodeInfo - voir UssdScreenDecisionTest.kt. */
internal fun decideScreenEvent(fieldCount: Int): UssdStepEvent {
    return if (fieldCount > 0) UssdStepEvent.NewField(fieldCount) else UssdStepEvent.FinalField
}

/** Pure, sans dépendance Android : un écran est considéré stable si son
 * empreinte n'a pas changé entre deux lectures séparées par
 * [UssdTimeouts.SCREEN_STABILIZATION_MS]. Utilisée identiquement pour la
 * détection de champs et pour la détection du résultat final - une seule
 * règle de stabilisation, jamais deux logiques différentes. */
internal fun isScreenStable(previousFingerprint: String?, currentFingerprint: String): Boolean {
    return previousFingerprint == currentFingerprint
}

// Vocabulaire générique de classification de résultat (Phase D3, point 18) -
// pas de logique par opérateur, à recalibrer après test réel. Top-level et
// `internal` (pas dans la classe/companion) précisément pour que
// classifyResult() soit testable en JUnit pur, sans toucher à
// AccessibilityService/Handler/Looper - voir ClassifyResultTest.kt.
internal val POSITIVE_RESULT_KEYWORDS = listOf(
    "succès", "success", "réussi", "reussi", "effectué", "effectue",
)
internal val NEGATIVE_RESULT_KEYWORDS = listOf(
    "échec", "echec", "échoué", "echoue", "insuffisant", "invalide",
    "annulé", "annule", "erreur", "impossible",
)

/** Heuristique de classification (Phase D3, point 18) - PAS une preuve, un
 * mot-clé au mieux (même niveau d'incertitude que apps.core.views.
 * _classify_failure_reason côté Backend). Ne suppose jamais SUCCESS par
 * défaut : ni signal reconnu, ni les deux signaux à la fois, ne produit
 * jamais un succès - un signal négatif l'emporte toujours sur un positif. */
internal sealed class ResultClassification {
    data class Recognized(val status: String) : ResultClassification()
    object Unrecognized : ResultClassification()
}

internal fun classifyResult(message: String): ResultClassification {
    val text = message.lowercase()
    val hasNegative = NEGATIVE_RESULT_KEYWORDS.any { text.contains(it) }
    val hasPositive = POSITIVE_RESULT_KEYWORDS.any { text.contains(it) }
    return when {
        hasNegative -> ResultClassification.Recognized("FAILED")
        hasPositive -> ResultClassification.Recognized("SUCCESS")
        else -> ResultClassification.Unrecognized
    }
}

/**
 * Moteur natif (Phase D3) : lit et manipule la boîte de dialogue USSD
 * système via l'arbre [AccessibilityNodeInfo], indépendamment du Flutter
 * Client et du Backend - aucun appel réseau, aucune donnée métier connue ici.
 *
 * Portée strictement limitée : ce service est un EXÉCUTEUR de bas niveau
 * (détecter/lire/écrire/cliquer/signaler), jamais un décideur. Il ne
 * contient et ne doit jamais contenir de logique par opérateur (pas de
 * `if operator == "Orange"`) ni de séquence de scénario codée en dur - ces
 * décisions reviennent au Backend, relayées par D4 (non couvert ici) via
 * [onBackendInput]/[onBackendDone].
 *
 * Le Gateway ne décide jamais seul qu'une étape de saisie est terminée :
 * [FinalField] signifie uniquement "plus aucune valeur à saisir", jamais
 * "transfert réussi". La classification SUCCESS/FAILED n'est produite
 * qu'après confirmation explicite du Backend via [onBackendDone] (voir
 * [backendConfirmedDone]) - avant cela, tout changement d'écran en
 * [UssdSessionState.WAITING_FOR_RESULT] est ignoré.
 *
 * Activation strictement manuelle par l'utilisateur (Réglages > Accessibilité)
 * - voir [isAccessibilityServiceEnabled]/[openAccessibilitySettings] : cette
 * classe ne tente jamais de s'auto-activer.
 *
 * Threading (Phase D3) : tout - événements système, timeouts,
 * [onBackendInput]/[onBackendDone]/[cancelActiveSession] - s'exécute sur le
 * thread principal (aucun Looper/thread supplémentaire introduit), ce qui
 * élimine par construction toute course entre un AccessibilityEvent entrant
 * et une commande venant de D4.
 *
 * Remplace intégralement l'ancienne API de test à valeur unique
 * ([UssdTestConfig]/`armTestSession`, Phase 8.2) - un seul mécanisme
 * d'armement existe désormais, voir [armSession].
 */
class UssdAccessibilityService : AccessibilityService() {

    private val timeoutHandler = Handler(Looper.getMainLooper())
    private var stateTimeoutRunnable: Runnable? = null
    private var sessionTimeoutRunnable: Runnable? = null
    private var stabilizationRunnable: Runnable? = null

    @Volatile private var state: UssdSessionState = UssdSessionState.IDLE
    private var config: UssdSessionConfig? = null
    private var lastScreenFingerprint: String? = null
    // Phase D3, correction stabilisation : empreinte en cours de
    // confirmation, distincte de lastScreenFingerprint (dernier écran
    // ENTIÈREMENT analysé) - jamais confondues, sinon un écran encore en
    // train de se stabiliser serait pris à tort pour un écran déjà traité.
    private var stabilizingFingerprint: String? = null
    private var iterationCount = 0

    /** Phase D3, règle critique : n'est mis à `true` que par [onBackendDone]
     * - tant que c'est `false`, aucun changement d'écran en
     * WAITING_FOR_RESULT n'est classifié. */
    private var backendConfirmedDone = false

    override fun onServiceConnected() {
        super.onServiceConnected()
        Log.i(TAG, "[USSD] service accessibilité connecté (état=$state)")
        instance = this
    }

    override fun onUnbind(intent: Intent?): Boolean {
        Log.i(TAG, "[USSD] service accessibilité désactivé par le système/l'utilisateur")
        cancelSession()
        instance = null
        return super.onUnbind(intent)
    }

    override fun onInterrupt() {
        Log.w(TAG, "[USSD] onInterrupt() appelé par le système")
    }

    // ---------------------------------------------------------------------
    // Événements accessibilité
    // ---------------------------------------------------------------------

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        event ?: return
        val currentState = state
        if (currentState == UssdSessionState.IDLE) return
        if (event.eventType != AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED &&
            event.eventType != AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED
        ) {
            return
        }
        // Jamais notre propre UI de debug : UssdTestActivity n'est pas une
        // candidate USSD, même si elle est visible pendant le test.
        if (event.packageName?.toString() == applicationContext.packageName) return

        val root = rootInActiveWindow ?: return
        Log.d(
            TAG,
            "[USSD] event type=${AccessibilityEvent.eventTypeToString(event.eventType)} " +
                "pkg=${event.packageName} cls=${event.className} état=$currentState",
        )

        when (currentState) {
            UssdSessionState.WAITING_FOR_USSD -> handleCandidateScreen(root)
            UssdSessionState.WAITING_FOR_NEXT_SCREEN -> handlePossibleNextScreen(root)
            UssdSessionState.WAITING_FOR_RESULT -> if (backendConfirmedDone) handlePossibleResultScreen(root)
            else -> Unit // READING_SCREEN/ENTERING_VALUES/SUBMITTING sont pilotés en interne
        }
    }

    // ---------------------------------------------------------------------
    // Machine d'état - démarrage / annulation
    // ---------------------------------------------------------------------

    private fun beginSession(newConfig: UssdSessionConfig) {
        val restartable = state == UssdSessionState.IDLE || state == UssdSessionState.FINISHED ||
            state == UssdSessionState.FAILED || state == UssdSessionState.TIMEOUT
        if (!restartable) {
            Log.w(TAG, "[USSD] armSession() ignoré - session déjà active (état=$state)")
            return
        }
        config = newConfig
        iterationCount = 0
        lastScreenFingerprint = null
        stabilizingFingerprint = null
        backendConfirmedDone = false
        transitionTo(UssdSessionState.STARTING)
        sessionTimeoutRunnable = Runnable { onSessionTimeout() }.also {
            timeoutHandler.postDelayed(it, UssdTimeouts.SESSION_MAX_MS)
        }
        Log.i(
            TAG,
            "[USSD] STARTING - session armée (slot=${newConfig.simSlot ?: "défaut"}), " +
                "en attente de l'écran USSD",
        )
        transitionTo(UssdSessionState.WAITING_FOR_USSD)
    }

    fun cancelSession() {
        cancelStateTimeout()
        cancelStabilization()
        sessionTimeoutRunnable?.let { timeoutHandler.removeCallbacks(it) }
        sessionTimeoutRunnable = null
        config = null
        lastScreenFingerprint = null
        stabilizingFingerprint = null
        backendConfirmedDone = false
        state = UssdSessionState.IDLE
        Log.i(TAG, "[USSD] session annulée manuellement")
    }

    // ---------------------------------------------------------------------
    // Lecture d'écran / détection de champs (NEW_FIELD)
    // ---------------------------------------------------------------------

    private fun handleCandidateScreen(root: AccessibilityNodeInfo) {
        if (!looksLikeUssdCandidate(root)) return
        beginScreenStabilization(root)
    }

    private fun handlePossibleNextScreen(root: AccessibilityNodeInfo) {
        val fingerprint = computeFingerprint(root)
        if (fingerprint == lastScreenFingerprint) return // événement redondant, contenu inchangé
        if (!hasNonEmptyText(root)) return
        beginScreenStabilization(root)
    }

    /** Phase D3, correction critique : un écran candidat - qu'il finisse
     * par contenir un champ ou non - n'est JAMAIS analysé sur sa première
     * apparition. Toujours stabilisé d'abord (même règle, un seul chemin,
     * pour NEW_FIELD comme pour FINAL_FIELD) - un rendu partiel (dialogue
     * encore en train de s'afficher) ne doit jamais produire un mauvais
     * comptage de champs ni un faux FINAL_FIELD. */
    private fun beginScreenStabilization(root: AccessibilityNodeInfo) {
        transitionTo(UssdSessionState.READING_SCREEN)
        stabilizingFingerprint = computeFingerprint(root)
        scheduleScreenStabilization()
    }

    private fun scheduleScreenStabilization() {
        cancelStabilization()
        val runnable = Runnable { confirmScreenStable() }
        stabilizationRunnable = runnable
        timeoutHandler.postDelayed(runnable, UssdTimeouts.SCREEN_STABILIZATION_MS)
    }

    private fun cancelStabilization() {
        stabilizationRunnable?.let { timeoutHandler.removeCallbacks(it) }
        stabilizationRunnable = null
    }

    private fun confirmScreenStable() {
        stabilizationRunnable = null
        if (state != UssdSessionState.READING_SCREEN) return // état déjà changé entre-temps
        val root = rootInActiveWindow
        if (root == null) {
            fail("ACCESSIBILITY_ERROR", "rootInActiveWindow indisponible pendant la stabilisation")
            return
        }
        val fingerprint = computeFingerprint(root)
        if (!isScreenStable(stabilizingFingerprint, fingerprint)) {
            // Écran encore en mouvement - reprend la stabilisation sur ce
            // nouveau contenu, ne conclut jamais rien tant que ce n'est pas stable.
            stabilizingFingerprint = fingerprint
            scheduleScreenStabilization()
            return
        }
        analyzeStableScreen(root)
    }

    /** Appelée une seule fois l'écran confirmé stable - décide NEW_FIELD ou
     * FINAL_FIELD via [decideScreenEvent] (fonction pure, voir sa doc). */
    private fun analyzeStableScreen(root: AccessibilityNodeInfo) {
        Log.i(TAG, "[USSD] écran stable - dump du nœud racine :")
        dumpTree(root, 0, intArrayOf(MAX_LOG_NODES))
        lastScreenFingerprint = computeFingerprint(root)

        iterationCount += 1
        if (iterationCount > MAX_ITERATIONS) {
            fail("MAX_ITERATIONS_EXCEEDED", "nombre maximal d'itérations dépassé ($MAX_ITERATIONS)")
            return
        }

        val fields = mutableListOf<AccessibilityNodeInfo>()
        findAllInputNodes(root, fields)
        when (val decision = decideScreenEvent(fields.size)) {
            is UssdStepEvent.NewField -> {
                Log.i(TAG, "[USSD] fieldCount=${decision.fieldCount}")
                transitionTo(UssdSessionState.WAITING_FOR_INPUT)
                emit(decision)
            }
            UssdStepEvent.FinalField -> {
                Log.i(TAG, "[USSD] écran stable sans champ - FINAL_FIELD")
                transitionTo(UssdSessionState.WAITING_FOR_RESULT)
                // FinalField signifie uniquement "plus rien à saisir" - jamais
                // "réussi", jamais "résultat arrivé" (voir doc de classe).
                emit(decision)
            }
            else -> Unit // decideScreenEvent() ne retourne jamais autre chose
        }
    }

    // ---------------------------------------------------------------------
    // Réception des valeurs Backend (INPUT)
    // ---------------------------------------------------------------------

    /** Appelée par D4 une fois que le Backend a répondu INPUT (Phase D3,
     * point 6) : relit systématiquement l'écran courant plutôt que de
     * réutiliser la liste comptée au moment du NEW_FIELD, puisque l'écran a
     * pu changer pendant l'aller-retour réseau. */
    private fun handleBackendInput(values: List<String>) {
        if (state != UssdSessionState.WAITING_FOR_INPUT) {
            Log.w(TAG, "[USSD] onBackendInput() ignoré - état inattendu ($state)")
            return
        }
        val root = rootInActiveWindow
        if (root == null) {
            fail("ACCESSIBILITY_ERROR", "rootInActiveWindow indisponible pour la saisie")
            return
        }
        val fields = mutableListOf<AccessibilityNodeInfo>()
        findAllInputNodes(root, fields)
        if (fields.size != values.size) {
            fail("INPUT_ERROR", "fieldCount=${fields.size} valuesCount=${values.size}")
            return
        }
        enterValuesAndSubmit(root, fields, values)
    }

    private fun enterValuesAndSubmit(
        root: AccessibilityNodeInfo,
        fields: List<AccessibilityNodeInfo>,
        values: List<String>,
    ) {
        transitionTo(UssdSessionState.ENTERING_VALUES)
        for (i in fields.indices) {
            val value = values[i]
            // Jamais la valeur en clair dans les logs (point 9) - seule sa
            // longueur est utile au diagnostic.
            Log.d(TAG, "[USSD] ENTERING_VALUES - fieldIndex=$i valueLength=${value.length}")
            val args = Bundle().apply {
                putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, value)
            }
            val written = fields[i].performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)
            if (!written) {
                fail("INPUT_ERROR", "ACTION_SET_TEXT a échoué sur fieldIndex=$i")
                return
            }
        }

        val button = findActionButton(root)
        if (button == null) {
            fail("SUBMIT_BUTTON_NOT_FOUND", "aucun bouton de validation détecté après saisie")
            return
        }
        transitionTo(UssdSessionState.SUBMITTING)
        Log.d(TAG, "[USSD] SUBMITTING - clic sur ${describeNode(button)}")
        val clicked = button.performAction(AccessibilityNodeInfo.ACTION_CLICK)
        if (!clicked) {
            fail("SUBMIT_BUTTON_NOT_FOUND", "ACTION_CLICK a échoué sur le bouton détecté")
            return
        }
        transitionTo(UssdSessionState.WAITING_FOR_NEXT_SCREEN)
    }

    // ---------------------------------------------------------------------
    // Confirmation Backend (DONE) et détection du résultat
    // ---------------------------------------------------------------------

    /** Phase D3, points 14-15 : arme la détection du résultat - ne
     * classifie jamais rien elle-même. Relit l'écran courant immédiatement
     * (le résultat a pu apparaître pendant l'aller-retour réseau vers le
     * Backend) mais passe toujours par la même stabilisation avant de
     * conclure quoi que ce soit. */
    private fun handleBackendDone() {
        if (state != UssdSessionState.WAITING_FOR_RESULT) {
            Log.w(TAG, "[USSD] onBackendDone() reçu dans un état inattendu ($state)")
            return
        }
        backendConfirmedDone = true
        Log.i(TAG, "[USSD] onBackendDone() confirmé - vérification de l'écran actuel")
        val root = rootInActiveWindow ?: return
        val fingerprint = computeFingerprint(root)
        if (!isScreenStable(lastScreenFingerprint, fingerprint) && hasNonEmptyText(root)) {
            stabilizingFingerprint = fingerprint
            scheduleResultStabilizationCheck()
        }
    }

    private fun handlePossibleResultScreen(root: AccessibilityNodeInfo) {
        val fingerprint = computeFingerprint(root)
        if (fingerprint == lastScreenFingerprint) return
        if (!hasNonEmptyText(root)) return
        stabilizingFingerprint = fingerprint
        scheduleResultStabilizationCheck()
    }

    private fun scheduleResultStabilizationCheck() {
        cancelStabilization()
        val runnable = Runnable { confirmResultScreen() }
        stabilizationRunnable = runnable
        timeoutHandler.postDelayed(runnable, UssdTimeouts.SCREEN_STABILIZATION_MS)
    }

    private fun confirmResultScreen() {
        stabilizationRunnable = null
        if (state != UssdSessionState.WAITING_FOR_RESULT) return
        val root = rootInActiveWindow
        if (root == null) {
            fail("ACCESSIBILITY_ERROR", "rootInActiveWindow indisponible pendant stabilisation du résultat")
            return
        }
        val fingerprint = computeFingerprint(root)
        if (!isScreenStable(stabilizingFingerprint, fingerprint)) {
            // Écran encore en mouvement - reprogramme, ne classe toujours rien.
            stabilizingFingerprint = fingerprint
            scheduleResultStabilizationCheck()
            return
        }
        lastScreenFingerprint = fingerprint
        val message = extractScreenText(root)
        val classification = classifyResult(message)
        transitionTo(UssdSessionState.FINISHED)
        when (classification) {
            is ResultClassification.Recognized -> {
                Log.i(TAG, "[USSD] FINISHED - résultat=${classification.status} (${message.length} caractère(s))")
                emit(UssdStepEvent.Result(classification.status, message))
            }
            is ResultClassification.Unrecognized -> {
                Log.w(TAG, "[USSD] FINISHED - résultat non reconnu (${message.length} caractère(s))")
                emit(UssdStepEvent.Failed("UNRECOGNIZED_RESULT", message))
            }
        }
        cleanupAfterTerminal()
    }

    // ---------------------------------------------------------------------
    // Échec / nettoyage / notification
    // ---------------------------------------------------------------------

    private fun fail(errorCode: String, reason: String) {
        transitionTo(UssdSessionState.FAILED)
        Log.w(TAG, "[USSD] FAILED - $errorCode - $reason")
        emit(UssdStepEvent.Failed(errorCode, reason))
        cleanupAfterTerminal()
    }

    private fun transitionTo(newState: UssdSessionState) {
        Log.i(TAG, "[USSD] transition $state -> $newState")
        state = newState
        scheduleStateTimeout(newState)
    }

    /** Phase D4: two independent, named listener slots rather than one -
     * [stepEventListener] stays reserved for the debug UI ([UssdTestActivity]),
     * [productionStepEventListener] is set by [GatewayForegroundService]'s
     * bridge to Dart. Neither ever silently overwrites the other (the bug a
     * single shared slot would have caused whenever the debug UI and the
     * production bridge were both active). */
    private fun emit(event: UssdStepEvent) {
        val handler = Handler(Looper.getMainLooper())
        stepEventListener?.let { listener -> handler.post { listener(event) } }
        productionStepEventListener?.let { listener -> handler.post { listener(event) } }
    }

    private fun cleanupAfterTerminal() {
        cancelStateTimeout()
        cancelStabilization()
        sessionTimeoutRunnable?.let { timeoutHandler.removeCallbacks(it) }
        sessionTimeoutRunnable = null
        config = null
        lastScreenFingerprint = null
        stabilizingFingerprint = null
        backendConfirmedDone = false
    }

    // ---------------------------------------------------------------------
    // Timeouts
    // ---------------------------------------------------------------------

    private fun scheduleStateTimeout(newState: UssdSessionState) {
        cancelStateTimeout()
        val delay = when (newState) {
            UssdSessionState.WAITING_FOR_USSD -> UssdTimeouts.WAITING_FOR_USSD_MS
            UssdSessionState.WAITING_FOR_INPUT -> UssdTimeouts.WAITING_FOR_INPUT_MS
            UssdSessionState.SUBMITTING -> UssdTimeouts.SUBMITTING_MS
            UssdSessionState.WAITING_FOR_NEXT_SCREEN -> UssdTimeouts.WAITING_FOR_NEXT_SCREEN_MS
            UssdSessionState.WAITING_FOR_RESULT -> UssdTimeouts.RESULT_TIMEOUT_MS
            else -> null
        } ?: return
        val runnable = Runnable { onStateTimeout(newState) }
        stateTimeoutRunnable = runnable
        timeoutHandler.postDelayed(runnable, delay)
    }

    private fun cancelStateTimeout() {
        stateTimeoutRunnable?.let { timeoutHandler.removeCallbacks(it) }
        stateTimeoutRunnable = null
    }

    private fun onStateTimeout(expectedState: UssdSessionState) {
        if (state != expectedState) return // déjà transitionné entre-temps, timeout obsolète
        state = UssdSessionState.TIMEOUT
        Log.w(TAG, "[USSD] TIMEOUT dans l'état $expectedState")
        emit(UssdStepEvent.Timeout)
        cleanupAfterTerminal()
    }

    private fun onSessionTimeout() {
        if (state == UssdSessionState.IDLE || state == UssdSessionState.FINISHED ||
            state == UssdSessionState.FAILED || state == UssdSessionState.TIMEOUT
        ) {
            return
        }
        state = UssdSessionState.TIMEOUT
        Log.w(TAG, "[USSD] TIMEOUT global de session (${UssdTimeouts.SESSION_MAX_MS} ms dépassés)")
        emit(UssdStepEvent.Timeout)
        cleanupAfterTerminal()
    }

    // ---------------------------------------------------------------------
    // Lecture de l'arbre AccessibilityNodeInfo
    // ---------------------------------------------------------------------

    /** Heuristique délibérément SANS package/classe codé en dur (voir la
     * doc de classe) : un écran "candidat" est un sous-arbre petit
     * (typique d'une boîte de dialogue) contenant au moins un texte non
     * vide. Seuil à confirmer/ajuster sur device réel. */
    private fun looksLikeUssdCandidate(root: AccessibilityNodeInfo): Boolean {
        val count = countNodes(root, MAX_CANDIDATE_NODES + 1)
        if (count > MAX_CANDIDATE_NODES) return false
        return hasNonEmptyText(root)
    }

    private fun countNodes(node: AccessibilityNodeInfo, limit: Int): Int {
        var count = 1
        if (count > limit) return count
        for (i in 0 until node.childCount) {
            val child = node.getChild(i) ?: continue
            count += countNodes(child, limit - count)
            if (count > limit) return count
        }
        return count
    }

    private fun hasNonEmptyText(node: AccessibilityNodeInfo): Boolean {
        if (!node.text.isNullOrBlank()) return true
        for (i in 0 until node.childCount) {
            val child = node.getChild(i) ?: continue
            if (hasNonEmptyText(child)) return true
        }
        return false
    }

    /** Message complet (Phase D3, point 17) : DFS, uniquement node.text,
     * déduplication CONSÉCUTIVE seulement (jamais globale, pour ne pas
     * supprimer à tort une répétition légitime dans le message), jamais
     * tronqué. */
    private fun extractScreenText(node: AccessibilityNodeInfo): String {
        val parts = mutableListOf<String>()
        collectText(node, parts)
        val sb = StringBuilder()
        var previous: String? = null
        for (part in parts) {
            if (part == previous) continue
            sb.append(part).append(' ')
            previous = part
        }
        return sb.toString().trim()
    }

    private fun collectText(node: AccessibilityNodeInfo, out: MutableList<String>) {
        node.text?.let { if (it.isNotBlank()) out.add(it.toString()) }
        for (i in 0 until node.childCount) {
            val child = node.getChild(i) ?: continue
            collectText(child, out)
        }
    }

    private fun computeFingerprint(node: AccessibilityNodeInfo): String {
        val sb = StringBuilder()
        appendFingerprint(node, sb)
        return sb.toString()
    }

    private fun appendFingerprint(node: AccessibilityNodeInfo, sb: StringBuilder) {
        sb.append(node.className).append('|').append(node.text).append(';')
        for (i in 0 until node.childCount) {
            val child = node.getChild(i) ?: continue
            appendFingerprint(child, sb)
        }
    }

    /** Dump borné (voir [MAX_LOG_NODES]) - texte/contentDescription/className/
     * éditable/cliquable/actions pour chaque nœud. */
    private fun dumpTree(node: AccessibilityNodeInfo, depth: Int, budget: IntArray) {
        if (budget[0] <= 0) return
        budget[0] -= 1
        Log.d(TAG, "[USSD] ${"  ".repeat(depth)}${describeNode(node)}")
        for (i in 0 until node.childCount) {
            val child = node.getChild(i) ?: continue
            dumpTree(child, depth + 1, budget)
        }
    }

    private fun describeNode(node: AccessibilityNodeInfo): String {
        val cls = node.className?.toString()?.substringAfterLast('.') ?: "?"
        val text = node.text?.toString().orEmpty()
        val desc = node.contentDescription?.toString().orEmpty()
        val actions = node.actionList.joinToString(",") { actionName(it.id) }
        return "class=$cls editable=${node.isEditable} clickable=${node.isClickable} " +
            "enabled=${node.isEnabled} text=\"$text\" desc=\"$desc\" actions=[$actions]"
    }

    private fun actionName(id: Int): String = when (id) {
        AccessibilityNodeInfo.ACTION_CLICK -> "CLICK"
        AccessibilityNodeInfo.ACTION_SET_TEXT -> "SET_TEXT"
        AccessibilityNodeInfo.ACTION_FOCUS -> "FOCUS"
        AccessibilityNodeInfo.ACTION_CLEAR_FOCUS -> "CLEAR_FOCUS"
        else -> "id=$id"
    }

    /** Détection multi-champs (Phase D3, point 4) : accumulation DFS,
     * jamais un arrêt au premier match - l'ordre de sortie est l'ordre
     * naturel du parcours de l'arbre, sans jamais lire de coordonnées
     * géométriques (voir le rapport d'audit D3, section G). */
    private fun findAllInputNodes(node: AccessibilityNodeInfo, out: MutableList<AccessibilityNodeInfo>) {
        val isInput = node.isEditable ||
            node.className?.toString()?.contains("EditText", ignoreCase = true) == true ||
            node.actionList.any { it.id == AccessibilityNodeInfo.ACTION_SET_TEXT }
        if (isInput) out.add(node)
        for (i in 0 until node.childCount) {
            val child = node.getChild(i) ?: continue
            findAllInputNodes(child, out)
        }
    }

    /** Détection multi-signal du bouton de validation : mots-clés
     * texte/contentDescription en premier, puis className *Button*, puis
     * "un seul candidat cliquable restant", et la position en tout dernier
     * recours seulement. */
    private fun findActionButton(root: AccessibilityNodeInfo): AccessibilityNodeInfo? {
        val candidates = mutableListOf<AccessibilityNodeInfo>()
        collectClickable(root, candidates)
        val nonNegative = candidates.filterNot { matchesKeyword(it, NEGATIVE_KEYWORDS) }

        nonNegative.firstOrNull { matchesKeyword(it, POSITIVE_KEYWORDS) }?.let { return it }
        nonNegative.firstOrNull {
            it.className?.toString().orEmpty().contains("Button", ignoreCase = true)
        }?.let { return it }
        if (nonNegative.size == 1) return nonNegative[0]

        // Dernier recours : position (dernier nœud cliquable non-négatif
        // rencontré en parcours DFS) - non fiable, à confirmer sur device réel.
        return nonNegative.lastOrNull() ?: candidates.lastOrNull()
    }

    private fun collectClickable(node: AccessibilityNodeInfo, out: MutableList<AccessibilityNodeInfo>) {
        if (node.isClickable && node.isEnabled) out.add(node)
        for (i in 0 until node.childCount) {
            val child = node.getChild(i) ?: continue
            collectClickable(child, out)
        }
    }

    private fun matchesKeyword(node: AccessibilityNodeInfo, keywords: List<String>): Boolean {
        val haystack = ((node.text?.toString().orEmpty()) + " " + (node.contentDescription?.toString().orEmpty()))
            .lowercase()
        return keywords.any { haystack.contains(it) }
    }

    companion object {
        private const val TAG = "UssdAccessibility"

        private const val MAX_CANDIDATE_NODES = 60
        private const val MAX_LOG_NODES = 80
        private const val MAX_ITERATIONS = 6

        // Vocabulaire d'UI générique (pas de logique métier/opérateur).
        private val POSITIVE_KEYWORDS = listOf(
            "ok", "envoyer", "valider", "confirmer", "composer", "continuer",
            "send", "submit", "yes", "continue",
        )
        private val NEGATIVE_KEYWORDS = listOf(
            "annuler", "fermer", "non", "cancel", "close", "no", "dismiss",
        )

        @Volatile private var instance: UssdAccessibilityService? = null
        @Volatile private var stepEventListener: ((UssdStepEvent) -> Unit)? = null
        @Volatile private var productionStepEventListener: ((UssdStepEvent) -> Unit)? = null

        val isServiceRunning: Boolean get() = instance != null

        /** Debug UI only ([UssdTestActivity]) - see [emit]'s doc for why this
         * is a separate slot from [setProductionStepEventListener]. */
        fun setStepEventListener(listener: ((UssdStepEvent) -> Unit)?) {
            stepEventListener = listener
        }

        /** Phase D4: [GatewayForegroundService]'s bridge to Dart registers
         * here - separate slot from [setStepEventListener] so the debug UI
         * and the production bridge can never silently evict each other. */
        fun setProductionStepEventListener(listener: ((UssdStepEvent) -> Unit)?) {
            productionStepEventListener = listener
        }

        fun currentState(): UssdSessionState = instance?.state ?: UssdSessionState.IDLE

        /** Retourne false si le service n'est pas lié (non activé dans
         * Réglages) - l'appelant doit vérifier [isAccessibilityServiceEnabled]
         * avant d'appeler ceci, mais ce garde-fou reste nécessaire côté service. */
        fun armSession(config: UssdSessionConfig): Boolean {
            val svc = instance
            if (svc == null) {
                Log.w(TAG, "[USSD] armSession() appelé mais le service n'est pas actif")
                return false
            }
            svc.beginSession(config)
            return true
        }

        fun onBackendInput(values: List<String>) {
            instance?.handleBackendInput(values)
        }

        fun onBackendDone() {
            instance?.handleBackendDone()
        }

        fun cancelActiveSession() {
            instance?.cancelSession()
        }

        /** Implémentation standard (lecture de Settings.Secure, comparaison
         * de ComponentName) - volontairement robuste face au bug connu
         * (NPE) trouvé dans l'équivalent de la bibliothèque ussd_advanced
         * lors de l'audit précédent. */
        fun isAccessibilityServiceEnabled(context: Context): Boolean {
            val expected = ComponentName(context, UssdAccessibilityService::class.java)
            val enabledServices = Settings.Secure.getString(
                context.contentResolver,
                Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES,
            ) ?: return false
            val splitter = TextUtils.SimpleStringSplitter(':')
            splitter.setString(enabledServices)
            while (splitter.hasNext()) {
                val component = ComponentName.unflattenFromString(splitter.next())
                if (component == expected) return true
            }
            return false
        }

        /** Ouvre l'écran système - ne tente JAMAIS d'activer le service
         * automatiquement. */
        fun openAccessibilitySettings(context: Context) {
            val intent = Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            context.startActivity(intent)
        }
    }
}

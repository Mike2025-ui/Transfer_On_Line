package com.example.gateway_apk

import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.util.Log
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Gestionnaire d'overlay système (TYPE_APPLICATION_OVERLAY).
 *
 * Responsabilité unique : Recouvrir visuellement la fenêtre native
 * `com.android.phone` lors de l'exécution d'une session USSD sur le Gateway dédié,
 * et afficher à la place la console Transfer On Line.
 *
 * Ne contient aucune logique métier USSD : se contente d'écouter les [UssdStepEvent]
 * émis par [UssdAccessibilityService] et de les restituer visuellement.
 * Le bouton "Annuler" invoque directement [UssdAccessibilityService.cancelActiveSession].
 */
object UssdOverlayManager {
    private const val TAG = "UssdOverlayManager"

    private var windowManager: WindowManager? = null
    private var overlayView: View? = null
    private var isShowing = false

    // Composants UI de l'overlay
    private var stateBadge: TextView? = null
    private var stepBadge: TextView? = null
    private var operatorMessageText: TextView? = null
    private var lastResponseText: TextView? = null
    private var historyText: TextView? = null
    private var historyScrollView: ScrollView? = null
    private var closeButton: Button? = null

    private var currentStep = 0
    private val historyEntries = mutableListOf<String>()
    private val timeFormat = SimpleDateFormat("HH:mm:ss", Locale.getDefault())
    private val mainHandler = Handler(Looper.getMainLooper())
    private var autoDismissRunnable: Runnable? = null

    /** Vérifie si la permission SYSTEM_ALERT_WINDOW est accordée. */
    fun canDrawOverlays(context: Context): Boolean {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            Settings.canDrawOverlays(context)
        } else {
            true
        }
    }

    /** Ouvre l'écran des Réglages système Android pour accorder la permission de superposition. */
    fun openOverlaySettings(context: Context) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            val intent = Intent(
                Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                Uri.parse("package:${context.packageName}"),
            ).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            try {
                context.startActivity(intent)
            } catch (e: Exception) {
                Log.e(TAG, "Impossible d'ouvrir les paramètres d'overlay : ${e.message}")
            }
        }
    }

    /**
     * Affiche l'overlay de suivi Transfer On Line par-dessus l'écran (et masque com.android.phone).
     */
    fun show(context: Context, code: String? = null, slot: Int? = null) {
        mainHandler.post {
            if (!canDrawOverlays(context)) {
                Log.w(TAG, "show() ignoré : permission SYSTEM_ALERT_WINDOW non accordée")
                return@post
            }

            cancelAutoDismiss()
            currentStep = 0
            historyEntries.clear()

            if (isShowing && overlayView != null) {
                // Déjà affiché, réinitialisation des contenus
                resetContent(code, slot)
                return@post
            }

            try {
                val wm = context.getSystemService(Context.WINDOW_SERVICE) as WindowManager
                windowManager = wm

                val view = buildOverlayView(context)
                overlayView = view

                val layoutType = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
                } else {
                    @Suppress("DEPRECATION")
                    WindowManager.LayoutParams.TYPE_PHONE
                }

                val params = WindowManager.LayoutParams(
                    WindowManager.LayoutParams.MATCH_PARENT,
                    WindowManager.LayoutParams.MATCH_PARENT,
                    layoutType,
                    WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
                        WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
                    PixelFormat.TRANSLUCENT,
                ).apply {
                    gravity = Gravity.CENTER
                }

                wm.addView(view, params)
                isShowing = true
                resetContent(code, slot)
                Log.i(TAG, "Overlay USSD affiché au premier plan (TYPE_APPLICATION_OVERLAY)")
            } catch (e: Exception) {
                Log.e(TAG, "Erreur lors de l'affichage de l'overlay : ${e.message}", e)
            }
        }
    }

    /**
     * Met à jour les éléments de la console en réaction à un événement USSD.
     */
    fun update(event: UssdStepEvent) {
        mainHandler.post {
            if (!isShowing) return@post

            when (event) {
                is UssdStepEvent.NewField -> {
                    currentStep += 1
                    updateStateBadge("ATTENTE OPÉRATEUR", "#EA580C")
                    stepBadge?.text = "Étape $currentStep"
                    val msg = if (event.operatorMessage.isNotBlank()) event.operatorMessage else "Menu reçu de l'opérateur"
                    operatorMessageText?.text = msg
                    lastResponseText?.text = "En attente de saisie..."
                    addHistoryLog("Étape $currentStep — Message opérateur :\n« $msg »")
                }
                is UssdStepEvent.InputSubmitted -> {
                    updateStateBadge("SAISIE EN COURS", "#7C3AED")
                    val responseVal = if (event.isSecret) "•••• (CODE_DISTRIBUTEUR sécurisé)" else event.values.joinToString(", ")
                    lastResponseText?.text = "> $responseVal"
                    addHistoryLog("Réponse envoyée :\n> $responseVal")
                }
                is UssdStepEvent.FinalField -> {
                    updateStateBadge("FINALISATION", "#2563EB")
                    if (event.operatorMessage.isNotBlank()) {
                        operatorMessageText?.text = event.operatorMessage
                    }
                    lastResponseText?.text = "Traitement final..."
                    addHistoryLog("Écran final atteint.")
                }
                is UssdStepEvent.Result -> {
                    val isSuccess = event.status.equals("SUCCESS", ignoreCase = true)
                    val color = if (isSuccess) "#16A34A" else "#DC2626"
                    updateStateBadge(if (isSuccess) "SUCCÈS" else "ÉCHEC", color)
                    val msg = if (event.operatorMessage.isNotBlank()) event.operatorMessage else "Résultat : ${event.status}"
                    operatorMessageText?.text = msg
                    lastResponseText?.text = "Session terminée (${event.status})"
                    addHistoryLog("Résultat final : ${event.status}\n« $msg »")
                    onTerminalStateReached()
                }
                is UssdStepEvent.Failed -> {
                    updateStateBadge("ÉCHEC", "#DC2626")
                    val err = "Erreur: ${event.errorCode}\n${event.detail}"
                    operatorMessageText?.text = err
                    addHistoryLog("Session échouée (${event.errorCode}) : ${event.detail}")
                    onTerminalStateReached()
                }
                is UssdStepEvent.Timeout -> {
                    updateStateBadge("EXPIRÉ", "#991B1B")
                    operatorMessageText?.text = "Délai d'attente opérateur dépassé (TIMEOUT)"
                    addHistoryLog("Session expirée (TIMEOUT)")
                    onTerminalStateReached()
                }
            }
        }
    }

    /**
     * Ferme l'overlay immédiatement.
     */
    fun hide() {
        mainHandler.post {
            cancelAutoDismiss()
            if (!isShowing) return@post
            try {
                overlayView?.let { windowManager?.removeView(it) }
                Log.i(TAG, "Overlay USSD masqué et retiré du WindowManager")
            } catch (e: Exception) {
                Log.w(TAG, "Erreur lors du retrait de l'overlay : ${e.message}")
            } finally {
                overlayView = null
                isShowing = false
            }
        }
    }

    /**
     * Lors d'un état terminal, laisse l'affichage visible pendant 6 secondes
     * pour que l'opérateur lise le résultat, puis ferme l'overlay automatiquement.
     * Le bouton "Fermer" permet également une fermeture manuelle immédiate.
     */
    private fun onTerminalStateReached() {
        closeButton?.visibility = View.VISIBLE
        cancelAutoDismiss()
        val runnable = Runnable { hide() }
        autoDismissRunnable = runnable
        // 6 secondes pour garantir une lecture confortable du résultat final
        mainHandler.postDelayed(runnable, 6000L)
    }

    private fun cancelAutoDismiss() {
        autoDismissRunnable?.let { mainHandler.removeCallbacks(it) }
        autoDismissRunnable = null
    }

    private fun resetContent(code: String?, slot: Int?) {
        closeButton?.visibility = View.GONE
        operatorMessageText?.text = "Composition en cours..."
        lastResponseText?.text = "-"
        stepBadge?.text = "Initialisation"
        updateStateBadge("COMPOSITION EN COURS", "#0288D1")
        val info = "Session démarrée" + (if (code != null) " (Code: $code)" else "") + (if (slot != null) " [SIM $slot]" else "")
        addHistoryLog(info)
    }

    private fun addHistoryLog(entry: String) {
        val timestamp = timeFormat.format(Date())
        historyEntries.add("[$timestamp] $entry")
        historyText?.text = historyEntries.joinToString("\n\n")
        historyScrollView?.post {
            historyScrollView?.fullScroll(View.FOCUS_DOWN)
        }
    }

    private fun updateStateBadge(text: String, hexColor: String) {
        stateBadge?.text = text
        val drawable = GradientDrawable().apply {
            shape = GradientDrawable.RECTANGLE
            cornerRadius = 12f
            setColor(Color.parseColor(hexColor))
        }
        stateBadge?.background = drawable
        stateBadge?.setTextColor(Color.WHITE)
    }

    private fun buildOverlayView(context: Context): View {
        val density = context.resources.displayMetrics.density
        val dp = { value: Int -> (value * density).toInt() }

        // Conteneur principal opaque qui recouvre com.android.phone
        val root = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.parseColor("#0F172A")) // Fond sombre élégant et occultant
            setPadding(dp(18), dp(36), dp(18), dp(24))
        }

        // Header Title
        val titleText = TextView(context).apply {
            text = "Console d'Exécution USSD"
            textSize = 20f
            setTypeface(null, Typeface.BOLD)
            setTextColor(Color.WHITE)
        }
        root.addView(titleText)

        val subTitle = TextView(context).apply {
            text = "Transfer On Line — Passerelle Serveur Dédiée"
            textSize = 12f
            setTextColor(Color.parseColor("#94A3B8"))
            setPadding(0, dp(2), 0, dp(14))
        }
        root.addView(subTitle)

        // Bouton Annuler la session (Action immédiate)
        val cancelButton = Button(context).apply {
            text = "✕ ANNULER LA SESSION USSD"
            setBackgroundColor(Color.parseColor("#DC2626"))
            setTextColor(Color.WHITE)
            setTypeface(null, Typeface.BOLD)
            textSize = 14f
            val btnDrawable = GradientDrawable().apply {
                shape = GradientDrawable.RECTANGLE
                cornerRadius = 8f
                setColor(Color.parseColor("#DC2626"))
            }
            background = btnDrawable
            setOnClickListener {
                addHistoryLog("Annulation demandée par l'opérateur")
                updateStateBadge("ANNULÉ", "#991B1B")
                UssdAccessibilityService.cancelActiveSession()
                mainHandler.postDelayed({ hide() }, 1500L)
            }
        }
        root.addView(cancelButton)

        // Ligne d'états
        val statusRow = LinearLayout(context).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(0, dp(12), 0, dp(12))
            gravity = Gravity.CENTER_VERTICAL
        }

        val badge = TextView(context).apply {
            text = "EN COURS"
            textSize = 12f
            setTypeface(null, Typeface.BOLD)
            setPadding(dp(10), dp(4), dp(10), dp(4))
            val drawable = GradientDrawable().apply {
                shape = GradientDrawable.RECTANGLE
                cornerRadius = 12f
                setColor(Color.parseColor("#0288D1"))
            }
            background = drawable
            setTextColor(Color.WHITE)
        }
        stateBadge = badge
        statusRow.addView(badge)

        val stepView = TextView(context).apply {
            text = "Étape 1"
            textSize = 13f
            setTypeface(null, Typeface.BOLD)
            setTextColor(Color.parseColor("#E2E8F0"))
            setPadding(dp(12), 0, 0, 0)
        }
        stepBadge = stepView
        statusRow.addView(stepView)

        // Bouton Fermer (visible seulement en fin de session)
        val closeBtn = Button(context).apply {
            text = "Fermer"
            textSize = 12f
            setTextColor(Color.WHITE)
            val closeDrawable = GradientDrawable().apply {
                shape = GradientDrawable.RECTANGLE
                cornerRadius = 8f
                setColor(Color.parseColor("#475569"))
            }
            background = closeDrawable
            visibility = View.GONE
            setOnClickListener { hide() }
        }
        closeButton = closeBtn
        val closeParams = LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.WRAP_CONTENT,
            dp(36),
        ).apply {
            weight = 1f
            gravity = Gravity.END
        }
        statusRow.addView(closeBtn, closeParams)

        root.addView(statusRow)

        // Panneau Message Opérateur
        val messageContainer = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            val bg = GradientDrawable().apply {
                shape = GradientDrawable.RECTANGLE
                cornerRadius = 8f
                setColor(Color.parseColor("#1E293B"))
                setStroke(dp(1), Color.parseColor("#334155"))
            }
            background = bg
            setPadding(dp(14), dp(12), dp(14), dp(12))
        }

        val messageLabel = TextView(context).apply {
            text = "📡 MESSAGE OPÉRATEUR"
            textSize = 11f
            setTypeface(null, Typeface.BOLD)
            setTextColor(Color.parseColor("#38BDF8"))
        }
        messageContainer.addView(messageLabel)

        val messageContent = TextView(context).apply {
            text = "En attente de réponse réseau..."
            textSize = 14f
            setTypeface(Typeface.MONOSPACE)
            setTextColor(Color.parseColor("#F1F5F9"))
            setPadding(0, dp(6), 0, 0)
        }
        operatorMessageText = messageContent
        messageContainer.addView(messageContent)
        root.addView(messageContainer)

        // Panneau Réponse envoyée
        val responseContainer = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            val bg = GradientDrawable().apply {
                shape = GradientDrawable.RECTANGLE
                cornerRadius = 8f
                setColor(Color.parseColor("#1E293B"))
                setStroke(dp(1), Color.parseColor("#334155"))
            }
            background = bg
            setPadding(dp(14), dp(10), dp(14), dp(10))
        }
        val layoutParams = LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT,
            LinearLayout.LayoutParams.WRAP_CONTENT,
        ).apply {
            setMargins(0, dp(10), 0, dp(10))
        }

        val responseLabel = TextView(context).apply {
            text = "VALEUR / RÉPONSE ENVOYÉE"
            textSize = 11f
            setTypeface(null, Typeface.BOLD)
            setTextColor(Color.parseColor("#A78BFA"))
        }
        responseContainer.addView(responseLabel)

        val responseContent = TextView(context).apply {
            text = "-"
            textSize = 14f
            setTypeface(Typeface.MONOSPACE, Typeface.BOLD)
            setTextColor(Color.parseColor("#34D399"))
            setPadding(0, dp(4), 0, 0)
        }
        lastResponseText = responseContent
        responseContainer.addView(responseContent)
        root.addView(responseContainer, layoutParams)

        // Journal chronologique de la session
        val historyLabel = TextView(context).apply {
            text = "📋 HISTORIQUE DE LA SESSION"
            textSize = 12f
            setTypeface(null, Typeface.BOLD)
            setTextColor(Color.parseColor("#94A3B8"))
            setPadding(0, dp(4), 0, dp(4))
        }
        root.addView(historyLabel)

        val scrollView = ScrollView(context).apply {
            val bg = GradientDrawable().apply {
                shape = GradientDrawable.RECTANGLE
                cornerRadius = 8f
                setColor(Color.parseColor("#1E293B"))
                setStroke(dp(1), Color.parseColor("#334155"))
            }
            background = bg
            setPadding(dp(10), dp(10), dp(10), dp(10))
        }
        val scrollParams = LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT,
            0,
        ).apply {
            weight = 1f
        }

        val historyView = TextView(context).apply {
            text = "Session initialisée."
            textSize = 12f
            setTypeface(Typeface.MONOSPACE)
            setTextColor(Color.parseColor("#CBD5E1"))
        }
        historyText = historyView
        historyScrollView = scrollView
        scrollView.addView(historyView)
        root.addView(scrollView, scrollParams)

        return root
    }
}


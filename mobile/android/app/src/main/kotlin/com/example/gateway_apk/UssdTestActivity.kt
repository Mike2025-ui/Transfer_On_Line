package com.example.gateway_apk

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Console d'Exécution USSD — Transfer On Line
 *
 * Interface dédiée au serveur Gateway pour suivre en temps réel la session USSD :
 * - Maintien au premier plan pour remplacer visuellement la boîte de dialogue native Android
 * - Panneau dédié sous le bouton "Annuler la session" affichant :
 *   1. État de la session (IDLE, COMPOSITION EN COURS, ATTENTE OPÉRATEUR, etc.)
 *   2. Étape actuelle (Étape 1/3, etc.)
 *   3. Message complet reçu de l'opérateur (reproduction fidèle du menu USSD)
 *   4. Réponse / valeur envoyée
 *   5. Journal chronologique défilable de tous les échanges
 */
class UssdTestActivity : Activity() {

    private lateinit var codeInput: EditText
    private lateinit var slotInput: EditText
    private lateinit var accessibilityStatusText: TextView
    private lateinit var openAccessibilityButton: Button
    private lateinit var overlayStatusText: TextView
    private lateinit var openOverlayButton: Button

    private lateinit var stateBadge: TextView
    private lateinit var stepBadge: TextView
    private lateinit var operatorMessageText: TextView
    private lateinit var lastResponseText: TextView
    private lateinit var historyText: TextView
    private lateinit var historyScrollView: ScrollView

    private var currentStepNumber = 0
    private val historyEntries = mutableListOf<String>()
    private val timeFormat = SimpleDateFormat("HH:mm:ss", Locale.getDefault())

    private val pollHandler = Handler(Looper.getMainLooper())
    private var pollRunnable: Runnable? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        setContentView(buildLayout())

        UssdAccessibilityService.setStepEventListener { event ->
            runOnUiThread {
                bringConsoleToFront()
                handleUssdStepEvent(event)
            }
        }
        startPolling()
    }

    override fun onResume() {
        super.onResume()
        refreshAccessibilityStatus()
    }

    override fun onDestroy() {
        super.onDestroy()
        UssdAccessibilityService.setStepEventListener(null)
        stopPolling()
    }

    private fun bringConsoleToFront() {
        try {
            val frontIntent = Intent(this, UssdTestActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_REORDER_TO_FRONT or Intent.FLAG_ACTIVITY_SINGLE_TOP
            }
            startActivity(frontIntent)
        } catch (_: Exception) {}
    }

    private fun startPolling() {
        val runnable = object : Runnable {
            override fun run() {
                val serviceState = UssdAccessibilityService.currentState()
                if (serviceState == UssdSessionState.IDLE && currentStepNumber == 0 && stateBadge.text == "INITIALISATION") {
                    updateStateBadge("IDLE", "#64748B")
                }
                pollHandler.postDelayed(this, 600)
            }
        }
        pollRunnable = runnable
        pollHandler.post(runnable)
    }

    private fun stopPolling() {
        pollRunnable?.let { pollHandler.removeCallbacks(it) }
        pollRunnable = null
    }

    private fun handleUssdStepEvent(event: UssdStepEvent) {
        when (event) {
            is UssdStepEvent.NewField -> {
                currentStepNumber += 1
                updateStateBadge("ATTENTE OPÉRATEUR", "#EA580C")
                stepBadge.text = "Étape $currentStepNumber"
                val msg = if (event.operatorMessage.isNotBlank()) event.operatorMessage else "Menu reçu (saisie attendue)"
                operatorMessageText.text = msg
                lastResponseText.text = "En attente de réponse..."
                addHistoryLog("Étape $currentStepNumber\nOpérateur :\n« $msg »")
            }
            is UssdStepEvent.InputSubmitted -> {
                updateStateBadge("SAISIE EN COURS", "#7C3AED")
                val responseVal = event.values.joinToString(", ")
                lastResponseText.text = "> $responseVal"
                addHistoryLog("Réponse :\n> $responseVal")
            }
            is UssdStepEvent.FinalField -> {
                updateStateBadge("FINALISATION", "#2563EB")
                if (event.operatorMessage.isNotBlank()) {
                    operatorMessageText.text = event.operatorMessage
                }
                lastResponseText.text = "Traitement final..."
            }
            is UssdStepEvent.Result -> {
                val isSuccess = event.status.equals("SUCCESS", ignoreCase = true)
                if (isSuccess) {
                    updateStateBadge("SUCCÈS", "#16A34A")
                } else {
                    updateStateBadge("ÉCHEC", "#DC2626")
                }
                operatorMessageText.text = if (event.operatorMessage.isNotBlank()) event.operatorMessage else "Session terminée (${event.status})"
                addHistoryLog("Session terminée\nRésultat : ${if (isSuccess) "SUCCÈS" else "ÉCHEC"}\nMessage : ${event.operatorMessage}")
            }
            is UssdStepEvent.Failed -> {
                updateStateBadge("ÉCHEC", "#DC2626")
                val err = "Erreur: ${event.errorCode}\n${event.detail}"
                operatorMessageText.text = err
                addHistoryLog("Session échouée (${event.errorCode}) : ${event.detail}")
            }
            is UssdStepEvent.Timeout -> {
                updateStateBadge("EXPIRÉ", "#991B1B")
                operatorMessageText.text = "Délai d'attente opérateur dépassé (TIMEOUT)"
                addHistoryLog("Session expirée (TIMEOUT)")
            }
        }
    }

    private fun addHistoryLog(entry: String) {
        val timestamp = timeFormat.format(Date())
        historyEntries.add("[$timestamp] $entry")
        val fullText = historyEntries.joinToString("\n\n")
        historyText.text = fullText
        historyScrollView.post {
            historyScrollView.fullScroll(View.FOCUS_DOWN)
        }
    }

    private fun updateStateBadge(text: String, hexColor: String) {
        stateBadge.text = text
        val drawable = GradientDrawable().apply {
            shape = GradientDrawable.RECTANGLE
            cornerRadius = 12f
            setColor(Color.parseColor(hexColor))
        }
        stateBadge.background = drawable
        stateBadge.setTextColor(Color.WHITE)
    }

    private fun refreshAccessibilityStatus() {
        val enabled = UssdAccessibilityService.isAccessibilityServiceEnabled(this)
        if (enabled) {
            accessibilityStatusText.text = "● Service d'Accessibilité : ACTIVÉ"
            accessibilityStatusText.setTextColor(Color.parseColor("#16A34A"))
            openAccessibilityButton.visibility = View.GONE
        } else {
            accessibilityStatusText.text = "⚠️ Service d'Accessibilité : NON ACTIVÉ"
            accessibilityStatusText.setTextColor(Color.parseColor("#DC2626"))
            openAccessibilityButton.visibility = View.VISIBLE
        }

        val overlayEnabled = UssdOverlayManager.canDrawOverlays(this)
        if (overlayEnabled) {
            overlayStatusText.text = "● Superposition d'écran (Overlay) : ACTIVÉE"
            overlayStatusText.setTextColor(Color.parseColor("#16A34A"))
            openOverlayButton.visibility = View.GONE
        } else {
            overlayStatusText.text = "⚠️ Superposition d'écran : NON ACTIVÉE"
            overlayStatusText.setTextColor(Color.parseColor("#DC2626"))
            openOverlayButton.visibility = View.VISIBLE
        }
    }

    private fun buildLayout(): View {
        val density = resources.displayMetrics.density
        val dp = { value: Int -> (value * density).toInt() }

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.parseColor("#F8FAFC"))
            setPadding(dp(16), dp(16), dp(16), dp(24))
        }

        // Header Title
        val titleText = TextView(this).apply {
            text = "Console d'Exécution USSD"
            textSize = 20f
            setTypeface(null, Typeface.BOLD)
            setTextColor(Color.parseColor("#0F172A"))
        }
        root.addView(titleText)

        val subTitle = TextView(this).apply {
            text = "Transfer On Line — Passerelle Serveur Dédiée"
            textSize = 13f
            setTextColor(Color.parseColor("#64748B"))
            setPadding(0, dp(2), 0, dp(12))
        }
        root.addView(subTitle)

        // Accessibility & Overlay status card
        val accessCard = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            val bg = GradientDrawable().apply {
                setColor(Color.WHITE)
                cornerRadius = dp(8).toFloat()
                setStroke(dp(1), Color.parseColor("#E2E8F0"))
            }
            background = bg
            setPadding(dp(12), dp(10), dp(12), dp(10))
        }
        accessibilityStatusText = TextView(this).apply {
            text = "Vérification accessibilité..."
            textSize = 13f
            setTypeface(null, Typeface.BOLD)
        }
        accessCard.addView(accessibilityStatusText)

        openAccessibilityButton = Button(this).apply {
            text = "Activer dans Réglages > Accessibilité"
            textSize = 12f
            setTextColor(Color.WHITE)
            val btnBg = GradientDrawable().apply {
                setColor(Color.parseColor("#D97706"))
                cornerRadius = dp(6).toFloat()
            }
            background = btnBg
            val params = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
            ).apply { topMargin = dp(6) }
            layoutParams = params
            setOnClickListener { UssdAccessibilityService.openAccessibilitySettings(this@UssdTestActivity) }
        }
        accessCard.addView(openAccessibilityButton)

        // Overlay status section
        overlayStatusText = TextView(this).apply {
            text = "Vérification superposition d'écran..."
            textSize = 13f
            setTypeface(null, Typeface.BOLD)
            setPadding(0, dp(10), 0, 0)
        }
        accessCard.addView(overlayStatusText)

        openOverlayButton = Button(this).apply {
            text = "Autoriser 'Afficher sur les autres applis'"
            textSize = 12f
            setTextColor(Color.WHITE)
            val btnBg = GradientDrawable().apply {
                setColor(Color.parseColor("#0288D1"))
                cornerRadius = dp(6).toFloat()
            }
            background = btnBg
            val params = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
            ).apply { topMargin = dp(6) }
            layoutParams = params
            setOnClickListener { UssdOverlayManager.openOverlaySettings(this@UssdTestActivity) }
        }
        accessCard.addView(openOverlayButton)

        root.addView(accessCard)

        // Form Fields
        val codeLabel = TextView(this).apply {
            text = "Code USSD de commande :"
            textSize = 13f
            setTextColor(Color.parseColor("#334155"))
            setTypeface(null, Typeface.BOLD)
            setPadding(0, dp(12), 0, dp(4))
        }
        root.addView(codeLabel)

        codeInput = EditText(this).apply {
            hint = "Ex: *133# ou *123*1#"
            textSize = 15f
            setPadding(dp(12), dp(10), dp(12), dp(10))
            val bg = GradientDrawable().apply {
                setColor(Color.WHITE)
                cornerRadius = dp(8).toFloat()
                setStroke(dp(1), Color.parseColor("#CBD5E1"))
            }
            background = bg
        }
        root.addView(codeInput)

        val slotLabel = TextView(this).apply {
            text = "Slot SIM (0 ou 1, vide = défaut) :"
            textSize = 13f
            setTextColor(Color.parseColor("#334155"))
            setTypeface(null, Typeface.BOLD)
            setPadding(0, dp(10), 0, dp(4))
        }
        root.addView(slotLabel)

        slotInput = EditText(this).apply {
            hint = "Slot (défaut)"
            inputType = InputType.TYPE_CLASS_NUMBER
            textSize = 15f
            setPadding(dp(12), dp(10), dp(12), dp(10))
            val bg = GradientDrawable().apply {
                setColor(Color.WHITE)
                cornerRadius = dp(8).toFloat()
                setStroke(dp(1), Color.parseColor("#CBD5E1"))
            }
            background = bg
        }
        root.addView(slotInput)

        // Action Buttons
        val launchButton = Button(this).apply {
            text = "Lancer la session USSD"
            textSize = 15f
            setTextColor(Color.WHITE)
            setTypeface(null, Typeface.BOLD)
            val btnBg = GradientDrawable().apply {
                setColor(Color.parseColor("#1D4ED8"))
                cornerRadius = dp(8).toFloat()
            }
            background = btnBg
            val params = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
            ).apply { topMargin = dp(14) }
            layoutParams = params
            setOnClickListener { onArmAndDialClicked() }
        }
        root.addView(launchButton)

        val cancelButton = Button(this).apply {
            text = "Annuler la session"
            textSize = 14f
            setTextColor(Color.parseColor("#DC2626"))
            setTypeface(null, Typeface.BOLD)
            val btnBg = GradientDrawable().apply {
                setColor(Color.WHITE)
                cornerRadius = dp(8).toFloat()
                setStroke(dp(1), Color.parseColor("#FCA5A5"))
            }
            background = btnBg
            val params = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
            ).apply { topMargin = dp(8) }
            layoutParams = params
            setOnClickListener {
                UssdAccessibilityService.cancelActiveSession()
                updateStateBadge("ANNULÉE", "#DC2626")
                addHistoryLog("Session annulée par l'opérateur")
                Toast.makeText(this@UssdTestActivity, "Session annulée", Toast.LENGTH_SHORT).show()
            }
        }
        root.addView(cancelButton)

        // =====================================================================
        // CONSOLE DE SUIVI USSD DÉDIÉE (En dessous du bouton Annuler la session)
        // =====================================================================

        val divider = View(this).apply {
            setBackgroundColor(Color.parseColor("#CBD5E1"))
            val params = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                dp(1),
            ).apply { topMargin = dp(18); bottomMargin = dp(14) }
            layoutParams = params
        }
        root.addView(divider)

        // 1. État de la session & Étape courante
        val stateRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(0, 0, 0, dp(10))
        }

        stateBadge = TextView(this).apply {
            text = "IDLE"
            textSize = 12f
            setTypeface(null, Typeface.BOLD)
            setPadding(dp(12), dp(5), dp(12), dp(5))
            val bg = GradientDrawable().apply {
                setColor(Color.parseColor("#64748B"))
                cornerRadius = dp(12).toFloat()
            }
            background = bg
            setTextColor(Color.WHITE)
        }
        stateRow.addView(stateBadge)

        stepBadge = TextView(this).apply {
            text = "Étape : En attente"
            textSize = 13f
            setTypeface(null, Typeface.BOLD)
            setTextColor(Color.parseColor("#1E293B"))
            val params = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
            ).apply { leftMargin = dp(12) }
            layoutParams = params
        }
        stateRow.addView(stepBadge)
        root.addView(stateRow)

        // 2. Panneau Message Opérateur
        val operatorPanel = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            val bg = GradientDrawable().apply {
                setColor(Color.WHITE)
                cornerRadius = dp(10).toFloat()
                setStroke(dp(2), Color.parseColor("#3B82F6"))
            }
            background = bg
            setPadding(dp(14), dp(12), dp(14), dp(12))
        }

        val opHeaderRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(0, 0, 0, dp(8))
        }
        val opHeader = TextView(this).apply {
            text = "📡 MESSAGE OPÉRATEUR"
            textSize = 13f
            setTypeface(null, Typeface.BOLD)
            setTextColor(Color.parseColor("#1D4ED8"))
        }
        opHeaderRow.addView(opHeader)
        operatorPanel.addView(opHeaderRow)

        operatorMessageText = TextView(this).apply {
            text = "En attente de session USSD...\n(Les messages renvoyés par l'opérateur s'afficheront ici)"
            textSize = 14f
            setTextColor(Color.parseColor("#0F172A"))
            setTypeface(Typeface.MONOSPACE)
            setTextIsSelectable(true)
            setPadding(dp(8), dp(8), dp(8), dp(8))
            val msgBg = GradientDrawable().apply {
                setColor(Color.parseColor("#F1F5F9"))
                cornerRadius = dp(6).toFloat()
            }
            background = msgBg
        }
        operatorPanel.addView(operatorMessageText)

        // Section Réponse envoyée
        val responseContainer = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(0, dp(8), 0, 0)
        }
        val respLabel = TextView(this).apply {
            text = "Réponse envoyée : "
            textSize = 12f
            setTypeface(null, Typeface.BOLD)
            setTextColor(Color.parseColor("#475569"))
        }
        responseContainer.addView(respLabel)

        lastResponseText = TextView(this).apply {
            text = "-"
            textSize = 13f
            setTypeface(Typeface.MONOSPACE, Typeface.BOLD)
            setTextColor(Color.parseColor("#2563EB"))
        }
        responseContainer.addView(lastResponseText)
        operatorPanel.addView(responseContainer)

        root.addView(operatorPanel)

        // 3. Historique de la session (Journal chronologique défilable)
        val historyLabel = TextView(this).apply {
            text = "📋 HISTORIQUE DE LA SESSION"
            textSize = 13f
            setTextColor(Color.parseColor("#334155"))
            setTypeface(null, Typeface.BOLD)
            setPadding(0, dp(16), 0, dp(6))
        }
        root.addView(historyLabel)

        historyScrollView = ScrollView(this).apply {
            val params = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                dp(180),
            )
            layoutParams = params
            val bg = GradientDrawable().apply {
                setColor(Color.WHITE)
                cornerRadius = dp(8).toFloat()
                setStroke(dp(1), Color.parseColor("#E2E8F0"))
            }
            background = bg
            setPadding(dp(10), dp(10), dp(10), dp(10))
        }

        historyText = TextView(this).apply {
            text = "SESSION USSD\nAucune exécution pour le moment."
            textSize = 12f
            setTypeface(Typeface.MONOSPACE)
            setTextColor(Color.parseColor("#334155"))
            setTextIsSelectable(true)
        }
        historyScrollView.addView(historyText)
        root.addView(historyScrollView)

        return ScrollView(this).apply { addView(root) }
    }

    private fun onArmAndDialClicked() {
        if (!UssdAccessibilityService.isAccessibilityServiceEnabled(this)) {
            Toast.makeText(this, "Activez d'abord AccessibilityService dans Réglages", Toast.LENGTH_LONG).show()
            return
        }
        val code = codeInput.text.toString().trim()
        if (code.isEmpty()) {
            Toast.makeText(this, "Code USSD requis", Toast.LENGTH_SHORT).show()
            return
        }
        val slot = slotInput.text.toString().trim().toIntOrNull()

        if (!UssdOverlayManager.canDrawOverlays(this)) {
            Toast.makeText(this, "Autorisez 'Afficher sur les autres applis' pour masquer le dialogue natif", Toast.LENGTH_LONG).show()
            UssdOverlayManager.openOverlaySettings(this)
            return
        }

        if (!hasCallPermission()) {
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.CALL_PHONE), REQUEST_CALL_PERMISSION)
            Toast.makeText(this, "Autorisez l'appel puis relancez", Toast.LENGTH_LONG).show()
            return
        }

        currentStepNumber = 0
        historyEntries.clear()
        operatorMessageText.text = "Composition en cours..."
        lastResponseText.text = "-"
        stepBadge.text = "Initialisation"
        updateStateBadge("COMPOSITION EN COURS", "#0288D1")
        addHistoryLog("Session démarrée (Code: $code, Slot: ${slot ?: "défaut"})")

        // Déploie immédiatement l'overlay Transfer On Line pour recouvrir com.android.phone dès la composition
        UssdOverlayManager.show(this, code = code, slot = slot)
        UssdAccessibilityService.armSession(UssdSessionConfig(simSlot = slot))

        val intent = Intent(Intent.ACTION_CALL, Uri.parse("tel:" + Uri.encode(code)))
        try {
            startActivity(intent)
        } catch (error: Exception) {
            updateStateBadge("ÉCHEC", "#DC2626")
            operatorMessageText.text = "Erreur ACTION_CALL: ${error.message}"
            addHistoryLog("Échec de l'appel : ${error.message}")
            Toast.makeText(this, "Échec ACTION_CALL: ${error.message}", Toast.LENGTH_LONG).show()
        }
    }

    private fun hasCallPermission(): Boolean =
        ContextCompat.checkSelfPermission(this, Manifest.permission.CALL_PHONE) == PackageManager.PERMISSION_GRANTED

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQUEST_CALL_PERMISSION &&
            grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED
        ) {
            Toast.makeText(this, "Permission accordée, vous pouvez lancer la commande", Toast.LENGTH_SHORT).show()
        }
    }

    companion object {
        private const val REQUEST_CALL_PERMISSION = 9001
    }
}

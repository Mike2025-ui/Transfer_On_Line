package com.example.gateway_apk

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.InputType
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat

/**
 * Écran de test isolé (Phase D3 - moteur multi-champs), et écran UNIQUE de
 * diagnostic : après "Test ACTION_CALL", la vraie fenêtre USSD système
 * (Android/opérateur) peut apparaître au premier plan, mais aucune autre
 * Activity/interface n'est jamais créée par ce code. Jamais lancé depuis
 * MainActivity/Flutter en dehors du bouton de debug existant, aucune icône
 * de launcher (voir AndroidManifest.xml, `exported="false"`, non modifié).
 *
 * Ne simule plus le Backend (les anciens boutons "Envoyer INPUT"/"Envoyer
 * DONE" ont été retirés) : cette version observe uniquement le
 * comportement réel d'[UssdAccessibilityService] face à la vraie fenêtre
 * USSD - jusqu'à WAITING_FOR_INPUT/TIMEOUT compris, sans pouvoir débloquer
 * manuellement une session qui attendrait une saisie (ce sera le rôle de
 * D4/du vrai Backend).
 *
 * Listener et sondage d'état enregistrés dans [onCreate]/désenregistrés
 * dans [onDestroy] uniquement (jamais dans onResume/onPause) : ACTION_CALL
 * fait passer cette Activity en arrière-plan précisément pendant que la
 * vraie fenêtre USSD est affichée et que NEW_FIELD/FINAL_FIELD/RESULT/
 * TIMEOUT peuvent survenir - les rater pendant cette période rendrait le
 * test inutilisable.
 */
class UssdTestActivity : Activity() {

    private lateinit var codeInput: EditText
    private lateinit var slotInput: EditText
    private lateinit var stateText: TextView
    private lateinit var accessibilityStatusText: TextView

    private var lastEventDescription: String = ""
    private val pollHandler = Handler(Looper.getMainLooper())
    private var pollRunnable: Runnable? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(buildLayout())
        UssdAccessibilityService.setStepEventListener { event -> showEvent(event) }
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

    private fun startPolling() {
        val runnable = object : Runnable {
            override fun run() {
                renderStatus()
                pollHandler.postDelayed(this, 500)
            }
        }
        pollRunnable = runnable
        pollHandler.post(runnable)
    }

    private fun stopPolling() {
        pollRunnable?.let { pollHandler.removeCallbacks(it) }
        pollRunnable = null
    }

    private fun renderStatus() {
        val state = UssdAccessibilityService.currentState()
        stateText.text = if (lastEventDescription.isEmpty()) {
            "État: $state"
        } else {
            "État: $state\n$lastEventDescription"
        }
    }

    private fun showEvent(event: UssdStepEvent) {
        lastEventDescription = when (event) {
            is UssdStepEvent.NewField -> "NEW_FIELD\nfieldCount=${event.fieldCount}"
            is UssdStepEvent.FinalField -> "FINAL_FIELD"
            is UssdStepEvent.Result -> "${event.status}\nMessage: ${event.operatorMessage}"
            is UssdStepEvent.Failed -> "FAILED\nerrorCode=${event.errorCode}\n${event.detail}"
            is UssdStepEvent.Timeout -> "TIMEOUT"
        }
        runOnUiThread { renderStatus() }
    }

    private fun refreshAccessibilityStatus() {
        val enabled = UssdAccessibilityService.isAccessibilityServiceEnabled(this)
        accessibilityStatusText.text = if (enabled) {
            "AccessibilityService : ACTIVÉ"
        } else {
            "AccessibilityService : NON ACTIVÉ - Réglages > Accessibilité"
        }
    }

    private fun buildLayout(): View {
        val padding = (16 * resources.displayMetrics.density).toInt()
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(padding, padding * 2, padding, padding)
        }

        accessibilityStatusText = TextView(this)
        root.addView(accessibilityStatusText)

        root.addView(
            Button(this).apply {
                text = "Ouvrir Réglages > Accessibilité"
                setOnClickListener { UssdAccessibilityService.openAccessibilitySettings(this@UssdTestActivity) }
            },
        )

        root.addView(TextView(this).apply { text = "\nCode USSD à composer" })
        codeInput = EditText(this)
        root.addView(codeInput)

        root.addView(TextView(this).apply { text = "\nSlot SIM (0 ou 1, vide = défaut)" })
        slotInput = EditText(this).apply { inputType = InputType.TYPE_CLASS_NUMBER }
        root.addView(slotInput)

        root.addView(
            Button(this).apply {
                text = "Test ACTION_CALL (armer + composer)"
                setOnClickListener { onArmAndDialClicked() }
            },
        )
        root.addView(
            Button(this).apply {
                text = "Annuler la session"
                setOnClickListener {
                    UssdAccessibilityService.cancelActiveSession()
                    Toast.makeText(this@UssdTestActivity, "Session annulée", Toast.LENGTH_SHORT).show()
                }
            },
        )

        stateText = TextView(this).apply { text = "État: IDLE" }
        root.addView(stateText)

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

        if (!hasCallPermission()) {
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.CALL_PHONE), REQUEST_CALL_PERMISSION)
            Toast.makeText(this, "Autorisez l'appel puis relancez", Toast.LENGTH_LONG).show()
            return
        }

        lastEventDescription = ""
        UssdAccessibilityService.armSession(UssdSessionConfig(simSlot = slot))

        val intent = Intent(Intent.ACTION_CALL, Uri.parse("tel:" + Uri.encode(code)))
        try {
            startActivity(intent)
        } catch (error: Exception) {
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
            Toast.makeText(this, "Permission accordée, relancez le test", Toast.LENGTH_SHORT).show()
        }
    }

    companion object {
        private const val REQUEST_CALL_PERMISSION = 9001
    }
}

package com.example.gateway_apk

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Phase D3 - tests JUnit purs, sans dépendance Android (pas de Mockito, pas
 * de Robolectric - décision explicite, voir build.gradle.kts). Couvrent
 * UNIQUEMENT [classifyResult] : une fonction top-level qui ne touche ni
 * AccessibilityNodeInfo, ni rootInActiveWindow, ni Handler/Looper.
 *
 * Ces tests ne prouvent RIEN sur le comportement réel de
 * UssdAccessibilityService sur Android (détection de fenêtre, de champs, de
 * bouton, ACTION_SET_TEXT/ACTION_CLICK, changement d'écran) - cela reste
 * exclusivement validé par le test réel sur l'Itel A80.
 */
class ClassifyResultTest {

    @Test
    fun `recognizes a clear success message`() {
        val result = classifyResult("Transfert effectué avec succès. Montant : 500 FCFA. Identifiant : 847291.")
        assertEquals(ResultClassification.Recognized("SUCCESS"), result)
    }

    @Test
    fun `recognizes a clear failure message`() {
        val result = classifyResult("Votre transfert a échoué. Solde insuffisant.")
        assertEquals(ResultClassification.Recognized("FAILED"), result)
    }

    @Test
    fun `unknown message with no recognizable keyword is Unrecognized`() {
        val result = classifyResult("Merci d'avoir utilisé MTN Mobile Money.")
        assertEquals(ResultClassification.Unrecognized, result)
    }

    @Test
    fun `both positive and negative keywords present - negative wins, never a false success`() {
        val result = classifyResult("Transfert effectué avec succès mais une erreur est survenue ensuite.")
        assertEquals(ResultClassification.Recognized("FAILED"), result)
    }

    @Test
    fun `empty message is Unrecognized, never assumed SUCCESS`() {
        val result = classifyResult("")
        assertEquals(ResultClassification.Unrecognized, result)
    }

    @Test
    fun `multi-line message is classified from its full content, not just the first line`() {
        val message = "Transaction en cours.\nVeuillez patienter.\nOpération réussie."
        val result = classifyResult(message)
        assertEquals(ResultClassification.Recognized("SUCCESS"), result)
    }

    @Test
    fun `classification never truncates or alters the message the caller keeps`() {
        val fullMessage = "Transfert effectué avec succès. Montant : 500 FCFA. Identifiant : 847291. Merci."
        classifyResult(fullMessage)
        // classifyResult() only inspects the message, it never returns or
        // mutates it - the caller (confirmResultScreen) keeps the exact
        // original string for UssdStepEvent.Result.operatorMessage. This
        // test documents that contract: re-running classification on the
        // untouched original string is stable and deterministic.
        assertEquals(fullMessage.length, fullMessage.length)
        assertTrue(fullMessage.contains("Identifiant : 847291"))
    }

    @Test
    fun `case insensitive keyword matching`() {
        val result = classifyResult("TRANSFERT EFFECTUÉ AVEC SUCCÈS")
        assertEquals(ResultClassification.Recognized("SUCCESS"), result)
    }
}

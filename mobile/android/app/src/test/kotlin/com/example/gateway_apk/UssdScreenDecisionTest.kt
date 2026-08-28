package com.example.gateway_apk

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Phase D3 (correction stabilisation) - tests JUnit purs, sans dépendance
 * Android, pour [decideScreenEvent] et [isScreenStable] : les deux seules
 * fonctions qui décident "combien de champs -> quel événement" et
 * "l'écran a-t-il changé entre deux lectures". Aucun de ces tests ne
 * simule AccessibilityNodeInfo/rootInActiveWindow/findAllInputNodes - ils
 * ne prouvent donc rien sur le comportement réel d'AccessibilityService
 * sur Android. La détection réelle (fenêtre USSD, champs, stabilisation
 * en conditions réelles) n'est validée que sur l'Itel A80.
 */
class UssdScreenDecisionTest {

    @Test
    fun `one field detected produces NewField with fieldCount 1`() {
        val event = decideScreenEvent(1)
        assertEquals(UssdStepEvent.NewField(1), event)
    }

    @Test
    fun `two fields detected produces NewField with fieldCount 2`() {
        val event = decideScreenEvent(2)
        assertEquals(UssdStepEvent.NewField(2), event)
    }

    @Test
    fun `three fields detected produces NewField with fieldCount 3`() {
        val event = decideScreenEvent(3)
        assertEquals(UssdStepEvent.NewField(3), event)
    }

    @Test
    fun `zero fields produces FinalField, never NewField`() {
        val event = decideScreenEvent(0)
        assertEquals(UssdStepEvent.FinalField, event)
    }

    @Test
    fun `NewField always carries the exact real count, never a guessed default`() {
        for (count in 1..10) {
            val event = decideScreenEvent(count)
            assertTrue(event is UssdStepEvent.NewField)
            assertEquals(count, (event as UssdStepEvent.NewField).fieldCount)
        }
    }

    @Test
    fun `identical fingerprints are considered stable`() {
        assertTrue(isScreenStable("class=Dialog|text=Bienvenue;", "class=Dialog|text=Bienvenue;"))
    }

    @Test
    fun `different fingerprints are considered unstable - must re-check, never decide yet`() {
        assertFalse(isScreenStable("class=Dialog|text=Chargement...;", "class=Dialog|text=Bienvenue;"))
    }

    @Test
    fun `null previous fingerprint (first read) is never mistaken for stable`() {
        assertFalse(isScreenStable(null, "class=Dialog|text=Bienvenue;"))
    }
}

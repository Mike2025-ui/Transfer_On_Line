package com.example.gateway_apk

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * Phase D4.2 - tests JUnit purs pour [ussdStepEventToChannelMap], seule
 * logique nouvellement introduite côté GatewayForegroundService qui ne
 * dépend pas du framework Android (pas de Service, pas de FlutterEngine).
 * Vérifie uniquement la forme du Map envoyé sur le MethodChannel - le
 * round-trip réel (Kotlin -> MethodChannel -> Dart UssdStepEvent.fromChannelMap)
 * n'est prouvé que par le test sur l'Itel A80, jamais par ce fichier seul.
 */
class UssdStepEventChannelMapTest {

    @Test
    fun `NewField maps to type NEW_FIELD with the exact fieldCount and operatorMessage`() {
        val map = ussdStepEventToChannelMap(UssdStepEvent.NewField(3, "Menu principal"))
        assertEquals(mapOf("type" to "NEW_FIELD", "fieldCount" to 3, "operatorMessage" to "Menu principal"), map)
    }

    @Test
    fun `FinalField maps to type FINAL_FIELD with operatorMessage`() {
        val map = ussdStepEventToChannelMap(UssdStepEvent.FinalField("Traitement termine"))
        assertEquals(mapOf("type" to "FINAL_FIELD", "operatorMessage" to "Traitement termine"), map)
    }

    @Test
    fun `Result maps status and operatorMessage unchanged`() {
        val map = ussdStepEventToChannelMap(UssdStepEvent.Result("SUCCESS", "Transfert reussi"))
        assertEquals(
            mapOf("type" to "RESULT", "status" to "SUCCESS", "operatorMessage" to "Transfert reussi"),
            map,
        )
    }

    @Test
    fun `Failed maps errorCode and detail unchanged`() {
        val map = ussdStepEventToChannelMap(UssdStepEvent.Failed("WINDOW_LOST", "root became null"))
        assertEquals(
            mapOf("type" to "FAILED", "errorCode" to "WINDOW_LOST", "detail" to "root became null"),
            map,
        )
    }

    @Test
    fun `Timeout maps to a bare type TIMEOUT`() {
        val map = ussdStepEventToChannelMap(UssdStepEvent.Timeout)
        assertEquals(mapOf("type" to "TIMEOUT"), map)
    }

    @Test
    fun `InputSubmitted maps to type INPUT_SUBMITTED with values`() {
        val map = ussdStepEventToChannelMap(UssdStepEvent.InputSubmitted(listOf("1", "2"), isSecret = false))
        assertEquals(mapOf("type" to "INPUT_SUBMITTED", "values" to listOf("1", "2")), map)
    }
}

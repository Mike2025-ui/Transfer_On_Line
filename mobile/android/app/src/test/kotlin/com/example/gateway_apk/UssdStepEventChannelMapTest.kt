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
    fun `NewField maps to type NEW_FIELD with the exact fieldCount`() {
        val map = ussdStepEventToChannelMap(UssdStepEvent.NewField(3))
        assertEquals(mapOf("type" to "NEW_FIELD", "fieldCount" to 3), map)
    }

    @Test
    fun `FinalField maps to a bare type FINAL_FIELD`() {
        val map = ussdStepEventToChannelMap(UssdStepEvent.FinalField)
        assertEquals(mapOf("type" to "FINAL_FIELD"), map)
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
}

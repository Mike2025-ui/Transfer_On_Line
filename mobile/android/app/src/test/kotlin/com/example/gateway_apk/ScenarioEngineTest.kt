package com.example.gateway_apk

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Tests JUnit purs pour la logique de parsing et de résolution dynamique de ScenarioEngine.
 *
 * Vérifie :
 * 1. Désérialisation stricte du JSON synchronisé (version, étapes, types de champs).
 * 2. Prise en charge de AGENT_AUTH sans champs enfants.
 * 3. Résolution des variables dynamiques (numero, montant, forfait).
 */
class ScenarioEngineTest {

    @Test
    fun `parseScenariosFromJson parses scenario versions and steps correctly`() {
        val json = """
        {
            "scenarios": [
                {
                    "id": 10,
                    "version": 3,
                    "operator": "Orange",
                    "operator_code": "ORA_CI",
                    "service": "TRANSFER",
                    "service_code": "TRA",
                    "amount": 1000.0,
                    "label": "Transfert Orange Money",
                    "template": "*144*1*1*{numero}*{montant}#",
                    "is_active": true,
                    "steps": [
                        {
                            "order": 1,
                            "step_type": "INPUT",
                            "name": "Saisie Montant",
                            "fields": [
                                {"order": 1, "field_type": "DYNAMIC", "value": "montant"}
                            ]
                        },
                        {
                            "order": 2,
                            "step_type": "AGENT_AUTH",
                            "name": "Authentification Code Distributeur",
                            "fields": []
                        },
                        {
                            "order": 3,
                            "step_type": "FINAL_FIELD",
                            "name": "Confirmation",
                            "fields": []
                        }
                    ]
                }
            ]
        }
        """.trimIndent()

        val parsed = parseScenariosFromJson(json)
        assertEquals(1, parsed.size)

        val scenario = parsed[10]
        assertNotNull(scenario)
        assertEquals(10, scenario!!.id)
        assertEquals(3, scenario.version)
        assertEquals("Orange", scenario.operator)
        assertEquals(3, scenario.steps.size)

        val step1 = scenario.steps[0]
        assertEquals("INPUT", step1.stepType)
        assertEquals(1, step1.fields.size)
        assertEquals("DYNAMIC", step1.fields[0].fieldType)
        assertEquals("montant", step1.fields[0].value)

        val step2 = scenario.steps[1]
        assertEquals("AGENT_AUTH", step2.stepType)
        assertTrue(step2.fields.isEmpty())

        val step3 = scenario.steps[2]
        assertEquals("FINAL_FIELD", step3.stepType)
    }

    @Test
    fun `resolveDynamicVar correctly resolves standard transaction variables`() {
        val txData = mapOf(
            "recipient_phone" to "0701020304",
            "amount" to 5000.0,
            "service" to "PASS_INTERNET",
            "reference" to "REF-9988",
        )

        assertEquals("0701020304", resolveDynamicVar("numero", txData))
        assertEquals("0701020304", resolveDynamicVar("NUMERO", txData))
        assertEquals("5000", resolveDynamicVar("montant", txData))
        assertEquals("PASS_INTERNET", resolveDynamicVar("forfait", txData))
        assertEquals("REF-9988", resolveDynamicVar("reference", txData))
        assertNull(resolveDynamicVar("variable_inconnue", txData))
    }
}


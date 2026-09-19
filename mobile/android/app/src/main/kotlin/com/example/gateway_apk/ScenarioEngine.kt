package com.example.gateway_apk

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.ConcurrentHashMap

data class CachedField(
    val order: Int,
    val fieldType: String, // 'FIXED' or 'DYNAMIC'
    val value: String
)

data class CachedStep(
    val order: Int,
    val stepType: String, // 'INPUT', 'AGENT_AUTH', 'FINAL_FIELD'
    val name: String,
    val fields: List<CachedField>
)

data class CachedScenario(
    val id: Int,
    val version: Int,
    val operator: String,
    val operatorCode: String?,
    val service: String?,
    val serviceCode: String?,
    val amount: Double?,
    val label: String,
    val template: String,
    val isActive: Boolean,
    val steps: List<CachedStep>
)

sealed class SessionInitResult {
    data class Ready(val scenario: CachedScenario) : SessionInitResult()
    data class MissingScenario(val scenarioId: Int, val expectedVersion: Int) : SessionInitResult()
    data class VersionMismatch(val scenarioId: Int, val expectedVersion: Int, val cachedVersion: Int) : SessionInitResult()
    object InactiveScenario : SessionInitResult()
}

sealed class StepDecision {
    data class TypeInput(val values: List<String>, val stepOrder: Int, val stepName: String) : StepDecision()
    data class TypeAgentAuth(val code: String, val stepOrder: Int, val stepName: String) : StepDecision()
    data class AwaitFinal(val stepOrder: Int, val stepName: String) : StepDecision()
    data class Complete(val rawResponse: String, val isSuccess: Boolean) : StepDecision()
    data class Error(val message: String) : StepDecision()
}

/**
 * Moteur d'exécution local des scénarios USSD (Gateway Edge).
 *
 * Principes stricts :
 * 1. Déroule l'intégralité du scénario sans aucun appel réseau intermédiaire vers le Backend.
 * 2. Vérifie rigoureusement l'adéquation de version (interdit d'exécuter silencieusement une version obsolète).
 * 3. Lors de AGENT_AUTH, résout localement le CODE_DISTRIBUTEUR depuis DistributorCodeStore sans que
 *    le secret ne soit jamais exposé hors du processus de saisie.
 */
class ScenarioEngine(private val context: Context) {

    companion object {
        private const val PREFS_NAME = "tol_scenario_cache"
        private const val KEY_SCENARIOS_JSON = "cached_scenarios_json"

        @Volatile
        private var INSTANCE: ScenarioEngine? = null

        fun getInstance(context: Context): ScenarioEngine {
            return INSTANCE ?: synchronized(this) {
                INSTANCE ?: ScenarioEngine(context.applicationContext).also { INSTANCE = it }
            }
        }
    }

    private val cache = ConcurrentHashMap<Int, CachedScenario>()

    init {
        loadFromPrefs()
    }

    // --- État de session active en mémoire locale ---
    private var activeScenario: CachedScenario? = null
    private var activeTxData: Map<String, Any?> = emptyMap()
    private var activeSimSlot: Int = 0
    private var currentStepIndex: Int = 0

    /**
     * Met à jour le cache local à partir du JSON reçu de GET /api/scenarios/sync/.
     */
    @Synchronized
    fun updateCacheFromJson(jsonString: String): Int {
        val newMap = parseScenariosFromJson(jsonString)
        cache.clear()
        cache.putAll(newMap)

        // Persistance locale
        try {
            val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            prefs.edit().putString(KEY_SCENARIOS_JSON, jsonString).apply()
        } catch (_: Exception) {}

        return cache.size
    }

    private fun loadFromPrefs() {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val savedJson = prefs.getString(KEY_SCENARIOS_JSON, null) ?: return
        try {
            updateCacheFromJson(savedJson)
        } catch (_: Exception) {}
    }

    fun getScenario(scenarioId: Int): CachedScenario? = cache[scenarioId]

    fun hasScenarioVersion(scenarioId: Int, version: Int): Boolean {
        val scenario = cache[scenarioId] ?: return false
        return scenario.version == version
    }

    fun getCachedVersionsSummary(): Map<String, Int> {
        return cache.map { it.key.toString() to it.value.version }.toMap()
    }

    /**
     * Démarre une session d'exécution locale pour une transaction donnée.
     */
    @Synchronized
    fun startSession(
        scenarioId: Int,
        expectedVersion: Int,
        txData: Map<String, Any?>,
        simSlot: Int
    ): SessionInitResult {
        val scenario = cache[scenarioId] ?: return SessionInitResult.MissingScenario(scenarioId, expectedVersion)
        if (scenario.version != expectedVersion) {
            return SessionInitResult.VersionMismatch(scenarioId, expectedVersion, scenario.version)
        }
        if (!scenario.isActive) {
            return SessionInitResult.InactiveScenario
        }

        activeScenario = scenario
        activeTxData = txData
        activeSimSlot = simSlot
        currentStepIndex = 0

        return SessionInitResult.Ready(scenario)
    }

    /**
     * Analyse l'écran USSD courant et décide de l'action locale immédiate.
     */
    @Synchronized
    fun resolveNextAction(rawScreenContent: String): StepDecision {
        val scenario = activeScenario ?: return StepDecision.Error("Aucune session active dans ScenarioEngine")
        val steps = scenario.steps

        if (currentStepIndex >= steps.size) {
            // Toutes les étapes ont été déroulées
            return StepDecision.Complete(rawScreenContent, isSuccess = true)
        }

        val step = steps[currentStepIndex]

        when (step.stepType) {
            "INPUT" -> {
                val values = mutableListOf<String>()
                for (field in step.fields) {
                    if (field.fieldType == "DYNAMIC") {
                        val resolved = resolveDynamicVar(field.value, activeTxData)
                        if (resolved == null) {
                            return StepDecision.Error("Variable dynamique requise manquante : ${field.value}")
                        }
                        values.add(resolved)
                    } else {
                        values.add(field.value)
                    }
                }
                currentStepIndex++
                return StepDecision.TypeInput(values, step.order, step.name)
            }

            "AGENT_AUTH" -> {
                // Résolution strictement locale du CODE_DISTRIBUTEUR
                val secret = DistributorCodeStore.getDistributorCode(context, activeSimSlot)
                if (secret.isNullOrBlank()) {
                    return StepDecision.Error("CODE_DISTRIBUTEUR non configuré localement pour la SIM slot $activeSimSlot")
                }
                currentStepIndex++
                return StepDecision.TypeAgentAuth(secret, step.order, step.name)
            }

            "FINAL_FIELD" -> {
                currentStepIndex++
                return StepDecision.AwaitFinal(step.order, step.name)
            }

            else -> {
                return StepDecision.Error("Type d'étape inconnu : ${step.stepType}")
            }
        }
    }

    @Synchronized
    fun resetSession() {
        activeScenario = null
        activeTxData = emptyMap()
        activeSimSlot = 0
        currentStepIndex = 0
    }
}

/**
 * Fonction pure de désérialisation JSON -> Scénarios sans dépendance Android.
 * Testable directement sous JUnit pur.
 */
internal fun parseScenariosFromJson(jsonString: String): Map<Int, CachedScenario> {
    val root = JSONObject(jsonString)
    val array = root.optJSONArray("scenarios") ?: JSONArray()
    val newMap = mutableMapOf<Int, CachedScenario>()

    for (i in 0 until array.length()) {
        val sObj = array.getJSONObject(i)
        val stepsList = mutableListOf<CachedStep>()
        val stepsArr = sObj.optJSONArray("steps") ?: JSONArray()

        for (j in 0 until stepsArr.length()) {
            val stepObj = stepsArr.getJSONObject(j)
            val fieldsList = mutableListOf<CachedField>()
            val fieldsArr = stepObj.optJSONArray("fields") ?: JSONArray()

            for (k in 0 until fieldsArr.length()) {
                val fObj = fieldsArr.getJSONObject(k)
                fieldsList.add(
                    CachedField(
                        order = fObj.optInt("order", k + 1),
                        fieldType = fObj.optString("field_type", "FIXED"),
                        value = fObj.optString("value", "")
                    )
                )
            }

            stepsList.add(
                CachedStep(
                    order = stepObj.optInt("order", j + 1),
                    stepType = stepObj.optString("step_type", "INPUT"),
                    name = stepObj.optString("name", ""),
                    fields = fieldsList
                )
            )
        }

        val scenario = CachedScenario(
            id = sObj.getInt("id"),
            version = sObj.optInt("version", 1),
            operator = sObj.optString("operator", ""),
            operatorCode = if (sObj.isNull("operator_code")) null else sObj.optString("operator_code"),
            service = if (sObj.isNull("service")) null else sObj.optString("service"),
            serviceCode = if (sObj.isNull("service_code")) null else sObj.optString("service_code"),
            amount = if (sObj.has("amount") && !sObj.isNull("amount")) sObj.getDouble("amount") else null,
            label = sObj.optString("label", ""),
            template = sObj.optString("template", ""),
            isActive = sObj.optBoolean("is_active", true),
            steps = stepsList.sortedBy { it.order }
        )
        newMap[scenario.id] = scenario
    }
    return newMap
}

/**
 * Résolution pure des variables dynamiques d'une transaction.
 */
internal fun resolveDynamicVar(name: String, txData: Map<String, Any?>): String? {
    return when (name.lowercase()) {
        "numero" -> txData["recipient_phone"]?.toString() ?: txData["numero"]?.toString()
        "montant" -> {
            val m = txData["amount"] ?: txData["montant"]
            if (m is Double) m.toLong().toString() else m?.toString()
        }
        "forfait" -> txData["service"]?.toString() ?: txData["forfait"]?.toString()
        else -> txData[name]?.toString()
    }
}

package com.example.gateway_apk

import android.content.Context
import android.content.SharedPreferences
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * Stockage sécurisé et chiffré du CODE_DISTRIBUTEUR sur la Gateway Android.
 *
 * Utilise l'Android KeyStore matériel avec chiffrement AES/GCM/NoPadding (256-bit).
 * Le secret est cloisonné par slot SIM (slot 0 / slot 1).
 *
 * RÈGLES DE SÉCURITÉ ABSOLUES :
 * - Jamais transmis au Backend Django.
 * - Jamais consigné dans les logs, Logcat ou télémétrie.
 * - Restitué en mémoire vive uniquement à l'instant précis où l'étape AGENT_AUTH
 *   nécessite de renseigner le champ USSD.
 */
object DistributorCodeStore {

    private const val ANDROID_KEY_STORE = "AndroidKeyStore"
    private const val KEY_ALIAS = "TOL_Distributor_Secret_Key_v1"
    private const val PREFS_NAME = "tol_distributor_vault"
    private const val TRANSFORMATION = "AES/GCM/NoPadding"
    private const val GCM_IV_LENGTH = 12
    private const val GCM_TAG_LENGTH = 128

    private fun getOrCreateSecretKey(): SecretKey {
        val keyStore = KeyStore.getInstance(ANDROID_KEY_STORE).apply { load(null) }
        if (keyStore.containsAlias(KEY_ALIAS)) {
            val entry = keyStore.getEntry(KEY_ALIAS, null) as? KeyStore.SecretKeyEntry
            if (entry != null) {
                return entry.secretKey
            }
        }

        val keyGenerator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEY_STORE)
        val spec = KeyGenParameterSpec.Builder(
            KEY_ALIAS,
            KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT
        )
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setKeySize(256)
            .build()

        keyGenerator.init(spec)
        return keyGenerator.generateKey()
    }

    private fun getPrefs(context: Context): SharedPreferences {
        return context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
    }

    private fun slotKey(slot: Int): String = "secret_slot_$slot"

    /**
     * Enregistre et chiffre le code distributeur associé à un slot SIM spécifique.
     */
    @Synchronized
    fun saveDistributorCode(context: Context, slot: Int, code: String) {
        if (code.isBlank()) {
            clearDistributorCode(context, slot)
            return
        }

        try {
            val secretKey = getOrCreateSecretKey()
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(Cipher.ENCRYPT_MODE, secretKey)
            val iv = cipher.iv
            val encryptedBytes = cipher.doFinal(code.trim().toByteArray(Charsets.UTF_8))

            // Format binaire : [12 octets IV] + [données chiffrées + tag GCM]
            val combined = ByteArray(iv.size + encryptedBytes.size)
            System.arraycopy(iv, 0, combined, 0, iv.size)
            System.arraycopy(encryptedBytes, 0, combined, iv.size, encryptedBytes.size)

            val base64Ciphertext = Base64.encodeToString(combined, Base64.NO_WRAP)
            getPrefs(context).edit().putString(slotKey(slot), base64Ciphertext).apply()
        } catch (e: Exception) {
            // Silence tout détail sur le secret en cas d'erreur
        }
    }

    /**
     * Déchiffre et retourne en clair le code distributeur au moment de l'injection.
     */
    @Synchronized
    fun getDistributorCode(context: Context, slot: Int): String? {
        val base64Ciphertext = getPrefs(context).getString(slotKey(slot), null) ?: return null
        return try {
            val combined = Base64.decode(base64Ciphertext, Base64.NO_WRAP)
            if (combined.size <= GCM_IV_LENGTH) return null

            val iv = ByteArray(GCM_IV_LENGTH)
            val encryptedBytes = ByteArray(combined.size - GCM_IV_LENGTH)
            System.arraycopy(combined, 0, iv, 0, GCM_IV_LENGTH)
            System.arraycopy(combined, GCM_IV_LENGTH, encryptedBytes, 0, encryptedBytes.size)

            val secretKey = getOrCreateSecretKey()
            val cipher = Cipher.getInstance(TRANSFORMATION)
            val spec = GCMParameterSpec(GCM_TAG_LENGTH, iv)
            cipher.init(Cipher.DECRYPT_MODE, secretKey, spec)

            val decryptedBytes = cipher.doFinal(encryptedBytes)
            String(decryptedBytes, Charsets.UTF_8)
        } catch (e: Exception) {
            null
        }
    }

    /**
     * Vérifie si un code distributeur est configuré pour le slot donné, sans jamais
     * divulguer la valeur.
     */
    @Synchronized
    fun hasDistributorCode(context: Context, slot: Int): Boolean {
        val encrypted = getPrefs(context).getString(slotKey(slot), null)
        return !encrypted.isNullOrBlank()
    }

    /**
     * Supprime le code distributeur configuré pour un slot donné.
     */
    @Synchronized
    fun clearDistributorCode(context: Context, slot: Int) {
        getPrefs(context).edit().remove(slotKey(slot)).apply()
    }
}


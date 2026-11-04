package com.dsgpt.mobile

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import java.util.concurrent.TimeUnit
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject

fun serverOrigin(raw: String): String {
    val url = raw.toHttpUrl()
    if (BuildConfig.ACCEPTANCE && url.scheme == "http" && url.host == "127.0.0.1" &&
        url.username.isEmpty() && url.password.isEmpty() && url.encodedPath == "/" &&
        url.query == null && url.fragment == null) return url.toString().trimEnd('/')
    require(
        url.isHttps &&
            url.host.endsWith(".ts.net") &&
            url.username.isEmpty() &&
            url.password.isEmpty() &&
            url.encodedPath == "/" &&
            url.query == null &&
            url.fragment == null
    ) {
        "Use your PC's HTTPS Tailscale address without a path."
    }
    return url.toString().trimEnd('/')
}

fun setupPairing(origin: String?, code: String?): Pair<String, String>? = runCatching {
    val address = serverOrigin(origin ?: error("No setup address"))
    require(code != null && code.matches(Regex("[A-Za-z0-9_-]{6,128}")))
    address to code
}.getOrNull()

class Vault(context: Context) {
    private val prefs = context.getSharedPreferences("connection", Context.MODE_PRIVATE)

    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey("dsgpt-connection", null) as? SecretKey)?.let {
            return it
        }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
            .apply {
                init(
                    KeyGenParameterSpec.Builder(
                            "dsgpt-connection",
                            KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
                        )
                        .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                        .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                        .build()
                )
            }
            .generateKey()
    }

    fun save(origin: String, token: String) {
        val cipher =
            Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key()) }
        val encrypted =
            cipher.doFinal(
                JSONObject().put("origin", origin).put("token", token).toString().toByteArray()
            )
        check(
            prefs
                .edit()
                .putString("iv", Base64.encodeToString(cipher.iv, Base64.NO_WRAP))
                .putString("data", Base64.encodeToString(encrypted, Base64.NO_WRAP))
                .commit()
        ) {
            "Unable to save connection"
        }
    }

    fun revision(): String? = prefs.getString("data", null)?.let { saved ->
        java.security.MessageDigest.getInstance("SHA-256").digest(saved.toByteArray()).joinToString("") { "%02x".format(it) }
    }

    fun load(): Api? {
        val data = prefs.getString("data", null) ?: return null
        val iv = prefs.getString("iv", null) ?: error("Stored connection incomplete")
        val cipher =
            Cipher.getInstance("AES/GCM/NoPadding").apply {
                init(
                    Cipher.DECRYPT_MODE,
                    key(),
                    GCMParameterSpec(128, Base64.decode(iv, Base64.NO_WRAP)),
                )
            }
        val json = JSONObject(String(cipher.doFinal(Base64.decode(data, Base64.NO_WRAP))))
        return Api(serverOrigin(json.getString("origin")), json.getString("token"))
    }

    fun clear() {
        check(prefs.edit().clear().commit())
    }
}

class Api(val origin: String, private val token: String) {
    private val http =
        OkHttpClient.Builder().eventListenerFactory { MobileTelemetry.listener() }
            .followRedirects(false)
            .followSslRedirects(false)
            .proxy(java.net.Proxy.NO_PROXY)
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .build()

    // Only an explicit 401 permits replacing an expired credential. A network/TLS failure
    // must preserve the existing connection, not silently mint another device identity.
    suspend fun identityOrExpired(): JSONObject? = withContext(Dispatchers.IO) {
        val request = Request.Builder().url(origin + "/v1/device")
            .header("Authorization", "Bearer $token").build()
        http.newCall(request).execute().use { response ->
            if (response.code == 401) return@withContext null
            check(response.isSuccessful) { "Connection could not be verified" }
            val data = response.body?.string() ?: error("Empty identity")
            check(data.length <= 16384)
            JSONObject(data).also { check(it.getString("id").matches(Regex("[a-f0-9-]{36}"))) }
        }
    }

    suspend fun request(path: String, method: String = "GET", body: JSONObject? = null): String =
        withContext(Dispatchers.IO) {
            require(path.startsWith("/v1/") && !path.contains(".."))
            val request =
                Request.Builder()
                    .url(origin + path)
                    .header("Authorization", "Bearer $token")
                    .method(
                        method,
                        if (method == "GET") null
                        else
                            (body?.toString() ?: "{}").toRequestBody(
                                "application/json".toMediaType()
                            ),
                    )
                    .build()
            http.newCall(request).execute().use { response ->
                check(response.isSuccessful) {
                    if (response.code == 401) "Connection expired. Pair this phone again."
                    else {
                        val detail = try {
                            val input = response.body?.byteStream()
                            val data = java.io.ByteArrayOutputStream()
                            input?.use { source ->
                                val buffer = ByteArray(1024)
                                while(true) {
                                    val count = source.read(buffer); if(count < 0) break
                                    if(data.size() + count > 16384) { data.reset(); break }
                                    data.write(buffer, 0, count)
                                }
                            }
                            val value = JSONObject(data.toString("UTF-8")).opt("detail")
                            (if(value is String) value else (value as? JSONObject)?.optString("code"))?.take(300)
                        } catch(_: Exception) { null }
                        "Request failed (${response.code}). " + (detail?.takeIf { it.isNotBlank() } ?: "Refresh the current state before retrying.")
                    }
                }
                response.body?.string() ?: error("Empty server response")
            }
        }

    suspend fun download(id: String, sha256: String): ByteArray =
        withContext(Dispatchers.IO) {
            require(id.matches(Regex("[0-9a-f-]{36}")) && sha256.matches(Regex("[0-9a-f]{64}")))
            val request =
                Request.Builder()
                    .url("$origin/v1/diagnostics/exports/$id?sha256=$sha256")
                    .header("Authorization", "Bearer $token")
                    .build()
            http.newCall(request).execute().use { response ->
                check(response.isSuccessful) { "Preview expired. Preview again before saving." }
                response.body?.bytes() ?: error("Empty export")
            }
        }

    suspend fun downloadWork(id: String): ByteArray = withContext(Dispatchers.IO) {
        val request = Request.Builder().url("$origin/v1/work/tasks/${workTaskId(id)}/export")
            .header("Authorization", "Bearer $token").build()
        http.newCall(request).execute().use { response ->
            check(response.isSuccessful) { "Source download failed. Refresh the task and retry." }
            val body = response.body ?: error("Empty source archive")
            val result = java.io.ByteArrayOutputStream()
            body.byteStream().use { input ->
                val buffer = ByteArray(65536)
                while (true) {
                    val count = input.read(buffer); if (count < 0) break
                    check(result.size() + count <= 32 * 1024 * 1024) { "Source archive exceeds the download limit" }
                    result.write(buffer, 0, count)
                }
            }
            result.toByteArray()
        }
    }

    suspend fun downloadArtifact(task: String, artifact: WorkArtifact): ByteArray = withContext(Dispatchers.IO) {
        require(artifact.bytes in 0..256 * 1024 * 1024 && artifact.sha.matches(Regex("[0-9a-f]{64}"))) { "Invalid artifact metadata" }
        val request = Request.Builder().url("$origin/v1/work/tasks/${workTaskId(task)}/artifacts/${workTaskId(artifact.id)}")
            .header("Authorization", "Bearer $token").build()
        http.newCall(request).execute().use { response ->
            check(response.isSuccessful) { "Artifact download failed" }
            val result = java.io.ByteArrayOutputStream()
            (response.body ?: error("Empty artifact response")).byteStream().use { input ->
                val buffer = ByteArray(65536)
                while(true) {
                    val count = input.read(buffer); if(count < 0) break
                    check(result.size() + count <= artifact.bytes) { "Artifact size mismatch" }
                    result.write(buffer, 0, count)
                }
            }
            val bytes = result.toByteArray()
            val sha = java.security.MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
            check(bytes.size == artifact.bytes && sha == artifact.sha) { "Artifact integrity check failed" }
            bytes
        }
    }

    suspend fun downloadAttachment(chatId: String, id: String): ByteArray = withContext(Dispatchers.IO) {
        val request = Request.Builder().url("$origin/v1/conversations/${workTaskId(chatId)}/attachments/${workTaskId(id)}/download")
            .header("Authorization", "Bearer $token").build()
        http.newCall(request).execute().use { response ->
            check(response.isSuccessful) { "Attachment unavailable. Refresh history." }
            val result = java.io.ByteArrayOutputStream()
            (response.body ?: error("Empty attachment response")).byteStream().use { input ->
                val buffer = ByteArray(8192)
                while(true) { val count = input.read(buffer); if(count < 0) break
                    check(result.size() + count <= 524288) { "Attachment exceeds 512 KiB." }; result.write(buffer, 0, count)
                }
            }
            result.toByteArray()
        }
    }

    suspend fun downloadMemory(taskId: String?): ByteArray = withContext(Dispatchers.IO) {
        val query = if(taskId == null) "" else "?task_id=${workTaskId(taskId)}"
        val request = Request.Builder().url("$origin/v1/memories/export$query")
            .header("Authorization", "Bearer $token").build()
        http.newCall(request).execute().use { response ->
            check(response.isSuccessful) { "Memory export failed. Refresh and retry." }
            val result = java.io.ByteArrayOutputStream()
            (response.body ?: error("Empty memory export")).byteStream().use { input ->
                val buffer = ByteArray(65536)
                while(true) {
                    val count = input.read(buffer); if(count < 0) break
                    check(result.size() + count <= 32 * 1024 * 1024) { "Memory export exceeds the 32 MiB download limit" }
                    result.write(buffer, 0, count)
                }
            }
            result.toByteArray()
        }
    }

    companion object {
        suspend fun pair(raw: String, code: String): Api {
            val origin = serverOrigin(raw)
            val result =
                JSONObject(
                    Api(origin, "")
                        .request(
                            "/v1/pairings/redeem",
                            "POST",
                            JSONObject().put("code", code.trim()).put("name", "dsGPT Mobile"),
                        )
                )
            return Api(origin, result.getString("token"))
        }
    }

    fun persist(vault: Vault) = vault.save(origin, token)
}

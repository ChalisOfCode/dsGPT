package com.dsgpt.mobile

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.util.AtomicFile
import android.widget.TextView
import java.io.File
import kotlinx.coroutines.*
import org.json.JSONObject

/** Entry point for the already-authorized ADB shell, protected by DUMP in the manifest.
 * Ordinary launcher/deep-link intents never perform automatic pairing.
 */
class AutomaticPairingActivity : Activity() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(android.view.WindowManager.LayoutParams.FLAG_SECURE)
        val request = intent.getStringExtra("dsgpt_request") ?: ""
        val pairing = setupPairing(intent.getStringExtra("dsgpt_origin"), intent.getStringExtra("dsgpt_pairing"))
        intent.replaceExtras(Bundle())
        if (!request.matches(Regex("[a-f0-9]{32}")) || pairing == null) { finish(); return }
        setContentView(TextView(this).apply {
            text = "Connecting dsGPT to your desktop…"
            textSize = 20f
            gravity = android.view.Gravity.CENTER
            setPadding(32, 48, 32, 48)
        })
        scope.launch {
            val result = JSONObject().put("request", request)
            try {
                withTimeout(90_000) {
                    val vault = Vault(this@AutomaticPairingActivity)
                    val connected = automaticConnection(
                        pairing.first, vault::load, { it.origin },
                        { it.identityOrExpired()?.getString("id") },
                        { Api.pair(pairing.first, pairing.second) }, { it.persist(vault) },
                    )
                    result.put("status", connected.status)
                    connected.deviceId?.let { result.put("device_id", it) }
                }
            } catch (_: Exception) {
                // No tokens, one-use codes, server response bodies or exceptions in the bridge result.
                result.put("status", "connection_failed")
            }
            try {
                val file = AtomicFile(File(filesDir, "phone-connection-result.json"))
                val stream = file.startWrite()
                try { stream.write(result.toString().toByteArray()); file.finishWrite(stream) }
                catch (e: Exception) { file.failWrite(stream); throw e }
                if (result.optString("status") in setOf("paired", "reused")) {
                    startActivity(Intent(this@AutomaticPairingActivity, MainActivity::class.java)
                        .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_NEW_TASK))
                }
            } finally { finish() }
        }
    }

    override fun onDestroy() { scope.cancel(); super.onDestroy() }
}

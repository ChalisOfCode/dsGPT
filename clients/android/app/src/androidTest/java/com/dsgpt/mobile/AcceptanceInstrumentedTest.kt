package com.dsgpt.mobile

import androidx.lifecycle.Lifecycle
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.util.UUID

/** Runs only in the separately installed acceptance package, against synthetic PC data. */
@RunWith(AndroidJUnit4::class)
class AcceptanceInstrumentedTest {
    @Test fun connectedLifecycleAndCredentialPersistence() = runBlocking {
        assumeTrue(BuildConfig.ACCEPTANCE)
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val args = InstrumentationRegistry.getArguments()
        if (args.getString("phase") == "probe") {
            val origin = serverOrigin(args.getString("origin") ?: error("Missing probe endpoint"))
            var ready = false
            try {
                val connection = java.net.URL("$origin/v1/device").openConnection()
                    as java.net.HttpURLConnection
                try {
                    connection.connectTimeout = 3000
                    connection.readTimeout = 5000
                    connection.instanceFollowRedirects = false
                    ready = connection.responseCode == 401
                } finally { connection.disconnect() }
            } catch (_: java.io.IOException) { /* Readiness is retried by the PC runner. */ }
            File(context.filesDir, "acceptance-route.json").writeText(
                JSONObject().put("ready", ready).toString())
            return@runBlocking
        }
        val vault = Vault(context)
        if (args.getString("phase") == "restore") {
            val restored = vault.load() ?: error("Keystore credential lost across process exit/upgrade")
            assertTrue(JSONObject(restored.request("/v1/device")).has("id"))
            vault.clear()
            return@runBlocking
        }
        vault.clear()
        val origin = args.getString("origin") ?: error("Missing owned test endpoint")
        val code = args.getString("pairing") ?: error("Missing single-use pairing")
        val api = Api.pair(origin, code)
        api.persist(vault)
        assertEquals(serverOrigin(origin), vault.load()!!.origin)
        val device = JSONObject(api.request("/v1/device"))
        val chat = JSONObject(api.request("/v1/conversations", "POST",
            JSONObject().put("title", "Pixel acceptance synthetic chat")))
        val path = "/v1/conversations/${chat.getString("id")}/messages"
        val request = JSONObject().put("request_id", UUID.randomUUID().toString())
            .put("content", "Acceptance synthetic reply").put("model_id", "acceptance-fixture")
        val run = JSONObject(api.request(path, "POST", request))
        assertEquals(run.getString("id"), JSONObject(api.request(path, "POST", request)).getString("id"))
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            instrumentation.waitForIdleSync()
            scenario.moveToState(Lifecycle.State.CREATED)
            val deadline = android.os.SystemClock.elapsedRealtime() + 30000
            var status = ""
            while (android.os.SystemClock.elapsedRealtime() < deadline) {
                status = JSONObject(api.request("/v1/runs/${run.getString("id")}")).getString("status")
                if (status == "completed") break
                Thread.sleep(200)
            }
            assertEquals("Backend reply must continue while phone is backgrounded", "completed", status)
            scenario.moveToState(Lifecycle.State.RESUMED)
            scenario.recreate()
            val messages = org.json.JSONArray(api.request(path))
            assertEquals("No duplicate submission or lost reply", 2, messages.length())
            assertTrue(messages.getJSONObject(1).getString("content").contains("ACCEPTANCE"))
            val deadlineFrames = android.os.SystemClock.elapsedRealtime() + 15000
            while (MobileTelemetry.snapshot().optInt("frames_observed") == 0 &&
                android.os.SystemClock.elapsedRealtime() < deadlineFrames) Thread.sleep(100)
            val snapshot = MobileTelemetry.snapshot()
            assertTrue(snapshot.getInt("frames_observed") > 0)
            assertTrue(snapshot.getLong("memory_bytes") > 0)
            assertEquals("reachable", snapshot.getString("backend_reachability"))
            File(context.filesDir, "acceptance-phone.json").writeText(snapshot.toString(2))
            File(context.filesDir, "acceptance-phone.zip").writeBytes(phoneDiagnosticArchive(snapshot.toString(2)))
            File(context.filesDir, "acceptance-result.json").writeText(JSONObject()
                .put("passed", true).put("device_id", device.getString("id"))
                .put("background_reply_completed", true).put("duplicate_suppressed", true)
                .put("activity_recreated", true).put("keystore_saved", true).toString(2))
        }
    }
}

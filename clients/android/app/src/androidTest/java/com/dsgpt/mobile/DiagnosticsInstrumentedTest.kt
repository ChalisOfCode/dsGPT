package com.dsgpt.mobile

import androidx.lifecycle.Lifecycle
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.ByteArrayInputStream
import java.io.File
import java.security.MessageDigest
import java.util.zip.ZipInputStream

@RunWith(AndroidJUnit4::class)
class DiagnosticsInstrumentedTest {
    @Test fun nativeLifecycleFailureCollectionAndReviewedZipRunOnAndroid() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            val deadline = android.os.SystemClock.elapsedRealtime() + 15000
            while (MobileTelemetry.snapshot().optInt("frames_observed") == 0 &&
                android.os.SystemClock.elapsedRealtime() < deadline) {
                instrumentation.waitForIdleSync()
                Thread.sleep(100)
            }
            val initial = MobileTelemetry.snapshot()
            assertTrue("A real window frame must be observed", initial.getInt("frames_observed") > 0)
            assertTrue(initial.getDouble("startup_ms") >= 0)
            assertTrue(initial.getLong("memory_bytes") > 0)
            assertEquals(BuildConfig.VERSION_NAME, initial.getString("app_version"))

            scenario.moveToState(Lifecycle.State.CREATED)
            scenario.moveToState(Lifecycle.State.RESUMED)
            scenario.recreate()
            runBlocking {
                // No service listens here: exercise an actual failed transport, without an external host.
                runCatching { Api("https://127.0.0.1:1", "PRIVATE_TEST_TOKEN").request("/v1/device") }
                    .onSuccess { fail("Expected the deliberately unavailable local endpoint to fail") }
            }
            MobileTelemetry.record(DiagnosticEvent.HANDLED)
            val reviewed = MobileTelemetry.snapshot().toString(2)
            val snapshot = JSONObject(reviewed)
            assertEquals("unreachable", snapshot.getString("backend_reachability"))
            assertTrue(snapshot.getDouble("latency_ms") >= 0)
            assertTrue(snapshot.getJSONArray("failure_snapshots").length() > 0)
            assertTrue(snapshot.getJSONArray("timed_events").toString().contains("app_backgrounded"))
            assertFalse(reviewed.contains("PRIVATE_TEST_TOKEN"))
            assertFalse(reviewed.contains("127.0.0.1"))

            // Events after review must not silently change the exported snapshot.
            MobileTelemetry.record(DiagnosticEvent.UPLOAD)
            val zip = phoneDiagnosticArchive(reviewed)
            val files = linkedMapOf<String, ByteArray>()
            ZipInputStream(ByteArrayInputStream(zip)).use { input ->
                while (true) {
                    val entry = input.nextEntry ?: break
                    files[entry.name] = input.readBytes()
                }
            }
            val expected = JSONObject(reviewed).apply { remove("consent") }
            assertEquals(expected.toString(2), files.getValue("android/app-diagnostics.json").toString(Charsets.UTF_8))
            val manifest = JSONObject(files.getValue("manifest.json").toString(Charsets.UTF_8)).getJSONObject("files")
            files.filterKeys { it != "manifest.json" }.forEach { (name, bytes) ->
                val digest = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
                assertEquals(digest, manifest.getJSONObject(name).getString("sha256"))
                assertEquals(bytes.size, manifest.getJSONObject(name).getInt("bytes"))
            }
            File(instrumentation.targetContext.filesDir, "diagnostic-emulator.json").writeText(reviewed)
            File(instrumentation.targetContext.filesDir, "diagnostic-emulator.zip").writeBytes(zip)
            assertFalse("Diagnostics must not create a paired connection", Vault(instrumentation.targetContext).load() != null)
        }
    }
}

package com.dsgpt.mobile

import android.app.ActivityManager
import android.app.Application
import android.app.ApplicationExitInfo
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.os.Build
import android.os.Debug
import android.os.PowerManager
import android.os.SystemClock
import okhttp3.Call
import okhttp3.EventListener
import okhttp3.Response
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.time.Instant

class DsGptApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        MobileTelemetry.initialize(this)
    }
}

/** App-private diagnostics only. Nothing is transmitted until a reviewed snapshot is shared. */
object MobileTelemetry {
    private var app: Application? = null
    private var timeline = DiagnosticTimeline()
    private var failures = JSONArray()
    private var started = SystemClock.elapsedRealtime()
    private var startup: Double? = null
    private var frames = 0
    private var slowFrames = 0
    private var droppedFrames = 0
    private var firstBattery: Int? = null
    private var latency: Double? = null
    private var reachability = "not_measured"
    private var httpStatus: Int? = null
    private var crashHistoryAvailable = false
    private val lastFailure = mutableMapOf<DiagnosticEvent, Long>()
    private val prefs get() = app?.getSharedPreferences("diagnostic-history", Context.MODE_PRIVATE)

    @Synchronized fun initialize(application: Application) {
        if (app != null) return
        app = application
        started = SystemClock.elapsedRealtime()
        firstBattery = battery()
        runCatching {
            val saved = JSONArray(prefs?.getString("events", "[]"))
            for (i in maxOf(0, saved.length() - 100) until saved.length()) {
                val row = saved.getJSONObject(i)
                DiagnosticEvent.entries.find { it.code == row.optString("code") }?.let {
                    timeline.record(it, row.getString("captured_at"), row.optString("correlation_id").takeIf { id -> id.isNotBlank() && id != "null" })
                }
            }
            failures = JSONArray(prefs?.getString("failures", "[]"))
            while (failures.length() > 20) failures.remove(0)
        }
        record(DiagnosticEvent.STARTED)
        val previous = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, exception ->
            runCatching { record(DiagnosticEvent.CRASH) }
            if (previous != null) previous.uncaughtException(thread, exception)
            else { android.os.Process.killProcess(android.os.Process.myPid()); kotlin.system.exitProcess(10) }
        }
        // Android's own bounded history can report native crashes/ANRs after restart.
        if (Build.VERSION.SDK_INT >= 30) runCatching {
            val manager = application.getSystemService(ActivityManager::class.java)
            val last = prefs?.getLong("lastExit", 0L) ?: 0L
            val exits = manager.getHistoricalProcessExitReasons(application.packageName, 0, 5)
            crashHistoryAvailable = true
            exits.filter { it.timestamp > last }.sortedBy { it.timestamp }.forEach {
                val event = when (it.reason) {
                    ApplicationExitInfo.REASON_CRASH, ApplicationExitInfo.REASON_CRASH_NATIVE -> DiagnosticEvent.CRASH
                    ApplicationExitInfo.REASON_ANR -> DiagnosticEvent.ANR
                    ApplicationExitInfo.REASON_LOW_MEMORY -> DiagnosticEvent.LOW_MEMORY
                    else -> null
                }
                if (event != null) record(event, Instant.ofEpochMilli(it.timestamp).toString(), false)
            }
            exits.maxOfOrNull { it.timestamp }?.let { prefs?.edit()?.putLong("lastExit", it)?.apply() }
        }
    }

    @Synchronized fun record(event: DiagnosticEvent, at: String = Instant.now().toString(), currentMeasurements: Boolean = true, correlationId: String? = null) {
        timeline.record(event, at, correlationId)
        val failure = event !in setOf(DiagnosticEvent.STARTED, DiagnosticEvent.FOREGROUND, DiagnosticEvent.BACKGROUND)
        if (failure) {
            val now = SystemClock.elapsedRealtime()
            if (now - (lastFailure[event] ?: -60000L) >= 60000L) {
                lastFailure[event] = now
                failures.put(JSONObject().put("code", event.code).put("captured_at", at)
                    .put("correlation_id", correlationId)
                    .put("memory_bytes", if (currentMeasurements) memory() else null)
                    .put("latency_ms", if (currentMeasurements) latency else null))
                while (failures.length() > 20) failures.remove(0)
            }
        }
        val edit = prefs?.edit()?.putString("events", timedEvents().toString())
            ?.putString("failures", failures.toString())
        // Persist crash context before delegating to Android's normal termination handler.
        if (event == DiagnosticEvent.CRASH) edit?.commit() else edit?.apply()
    }

    @Synchronized fun frame(durationNanos: Long, dropped: Int) {
        if (durationNanos < 0) return
        if (startup == null) startup = (SystemClock.elapsedRealtime() - started).toDouble().coerceIn(0.0, 3600000.0)
        if (frames < Int.MAX_VALUE) frames++
        if (durationNanos > 32000000L && slowFrames < Int.MAX_VALUE) slowFrames++
        droppedFrames = (droppedFrames.toLong() + dropped.coerceAtLeast(0)).coerceAtMost(Int.MAX_VALUE.toLong()).toInt()
    }

    private fun memory(): Long? = runCatching { Debug.getPss().takeIf { it >= 0 }?.times(1024L) }.getOrNull()
    private fun battery(): Int? = runCatching {
        val status = app?.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED)) ?: return@runCatching null
        val level = status.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
        val scale = status.getIntExtra(BatteryManager.EXTRA_SCALE, -1)
        if (level >= 0 && scale > 0) ((level.toLong() * 100) / scale).toInt().coerceIn(0, 100) else null
    }.getOrNull()

    private fun timedEvents() = JSONArray().apply {
        timeline.snapshot().forEach { put(JSONObject().put("code", it.event.code).put("captured_at", it.at).put("correlation_id", it.correlationId)) }
    }

    @Synchronized fun snapshot(): JSONObject {
        val thermal = if (Build.VERSION.SDK_INT >= 29) runCatching {
            app?.getSystemService(PowerManager::class.java)?.currentThermalStatus?.takeIf { it in 0..6 }
        }.getOrNull() else null
        val currentBattery = battery()
        val usedMemory = memory()
        val limits = JSONArray().put("no_system_log_access").put("battery_delta_not_app_energy")
            .put("backend_probe_is_last_app_request")
        if (thermal == null) limits.put("thermal_unavailable")
        if (!crashHistoryAvailable) limits.put("crash_history_unavailable")
        if (frames == 0) limits.put("frame_metrics_unavailable")
        if (usedMemory == null) limits.put("memory_unavailable")
        return JSONObject().put("consent", true).put("captured_at", Instant.now().toString())
            .put("app_version", BuildConfig.VERSION_NAME).put("android_api", Build.VERSION.SDK_INT)
            .put("device_model", Build.MODEL.replace(Regex("[^A-Za-z0-9 ._()+?-]"), "?").take(80).ifBlank { "Unknown" })
            .put("memory_bytes", usedMemory).put("memory_measurement", "process_pss")
            .put("thermal_status", thermal).put("startup_ms", startup)
            .put("startup_measurement", "application_to_first_frame")
            .put("frames_observed", frames).put("frames_over_32ms", slowFrames).put("frame_reports_dropped", droppedFrames)
            .put("battery_level_percent", currentBattery)
            .put("battery_session_delta_percent", if (firstBattery != null && currentBattery != null) currentBattery - firstBattery!! else null)
            .put("latency_ms", latency).put("backend_reachability", reachability).put("last_http_status", httpStatus)
            .put("events", JSONArray(timeline.snapshot().map { it.event.code }))
            .put("timed_events", timedEvents()).put("failure_snapshots", JSONArray(failures.toString())).put("limitations", limits)
    }

    fun listener(): EventListener = object : EventListener() {
        private var start = 0L
        private var status: Int? = null
        override fun callStart(call: Call) { start = SystemClock.elapsedRealtime() }
        override fun responseHeadersEnd(call: Call, response: Response) { status = response.code }
        override fun callEnd(call: Call) { finish(call, false) }
        override fun callFailed(call: Call, ioe: IOException) { if (!call.isCanceled()) finish(call, true) }
        private fun finish(call: Call, failed: Boolean) {
            synchronized(MobileTelemetry) {
                latency = (SystemClock.elapsedRealtime() - start).toDouble().coerceIn(0.0, 3600000.0)
                reachability = if (failed && status == null) "unreachable" else "reachable"
                httpStatus = status
                if (failed || (status ?: 200) >= 400) {
                    val path = call.request().url.encodedPath
                    val event = when {
                        path.contains("/events") -> DiagnosticEvent.STREAM
                        path.contains("/export") || path.endsWith("/download") || path.contains("/artifacts/") -> DiagnosticEvent.DOWNLOAD
                        call.request().method == "POST" && (path.contains("/messages") || path.contains("/attachments") || path.contains("/documents")) -> DiagnosticEvent.UPLOAD
                        failed -> DiagnosticEvent.NETWORK
                        else -> DiagnosticEvent.SYNC
                    }
                    val id = path.split('/').lastOrNull { it.matches(Regex("[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")) }
                    record(event, correlationId = id)
                }
            }
        }
    }
}

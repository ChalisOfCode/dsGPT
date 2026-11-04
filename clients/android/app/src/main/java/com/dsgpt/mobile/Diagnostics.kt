package com.dsgpt.mobile

import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import org.json.JSONObject

@Composable
fun DiagnosticCategories(raw: String) {
    var expanded by remember { mutableStateOf("Overview") }
    val original = runCatching { JSONObject(raw) }.getOrNull()
    val files = original?.optJSONObject("files")
    val system = files?.optString("desktop/system-info.json")?.takeIf { it.isNotEmpty() }
        ?.let { runCatching { JSONObject(it) }.getOrNull() } ?: original
    if (system == null || !system.has("app_version")) {
        SelectionContainer { Text(raw) }
        return
    }
    fun selected(vararg keys: String): String {
        val result = JSONObject()
        keys.filter { system.has(it) }.forEach { result.put(it, system.get(it)) }
        return result.toString(2)
    }
    val categories = linkedMapOf(
        "Overview" to selected("app_version", "captured_at", "platform", "os_release", "database_version", "limitations"),
        "Application Health" to selected("running_replies", "work_capability", "code_execution_available", "startup_ms", "startup_measurement", "frames_observed", "frames_over_32ms", "frame_reports_dropped"),
        "Hardware Performance" to selected("architecture", "cpu_logical", "cpu_utilization_percent", "cpu_temperature_celsius", "ram_total_bytes", "ram_available_bytes", "process_rss_bytes", "disk_free_bytes", "gpu", "unavailable_measurements", "device_model", "android_api", "memory_bytes", "memory_measurement", "thermal_status", "battery_level_percent", "battery_session_delta_percent"),
        "AI Model and Inference" to selected("inference"),
        "Work Agent and Development" to selected("work"),
        "Network and Tailscale" to selected("network", "backend_reachability", "last_http_status", "latency_ms"),
        "Errors and Warnings" to selected("recent_errors", "failure_snapshots"),
        "Diagnostic History" to selected("snapshot_history", "timed_events"),
        "Advanced Logging" to selected("logging"),
    )
    if (files != null) categories["Export Diagnostics — complete preview"] = raw
    categories.forEach { (title, text) ->
        TextButton(onClick = { expanded = if (expanded == title) "" else title }) { Text(title) }
        if (expanded == title) SelectionContainer { Text(text) }
    }
}

fun phoneDiagnosticArchive(reviewed: String): ByteArray {
    val snapshot = JSONObject(reviewed).apply { remove("consent") }.toString(2)
    val summary = "# dsGPT Mobile diagnostics\n\nCollected: ${JSONObject(snapshot).getString("captured_at")}\n\n" +
        "Phone-only report. Measurements reflect the preview time. Battery change is for the whole device, " +
        "not an app energy estimate. Backend reachability reflects the last app request.\n"
    val files = linkedMapOf("summary.md" to summary, "android/app-diagnostics.json" to snapshot)
    val manifestFiles = JSONObject()
    files.forEach { (name, value) ->
        val bytes = value.toByteArray(Charsets.UTF_8)
        val sha = java.security.MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
        manifestFiles.put(name, JSONObject().put("bytes", bytes.size).put("sha256", sha))
    }
    files["manifest.json"] = JSONObject().put("schema_version", 1).put("privacy", "sanitized_allowlist")
        .put("files", manifestFiles).toString(2)
    val out = java.io.ByteArrayOutputStream()
    java.util.zip.ZipOutputStream(out).use { zip ->
        files.forEach { (name, value) ->
            zip.putNextEntry(java.util.zip.ZipEntry(name))
            zip.write(value.toByteArray(Charsets.UTF_8)); zip.closeEntry()
        }
    }
    return out.toByteArray()
}

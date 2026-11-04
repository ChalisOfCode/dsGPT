package com.dsgpt.mobile

import org.json.JSONObject

data class WorkTask(val id: String, val title: String, val requirements: String, val status: String,
    val revision: Int, val available: Boolean, val blocker: String?, val model: String,
    val step: Int, val summary: String, val failedSources: Int = 0, val referencesAvailable: Boolean = false, val target: String = "source", val buildReady: Boolean = false, val sourceManagement: Boolean = false, val publicResearch: String = "", val webMode: String = "off")
data class WorkArtifact(val id: String, val execution: String, val path: String, val bytes: Int, val sha: String)
data class WorkReceipt(val id: String, val step: Int, val status: String, val snapshot: String, val cleanup: Boolean)
data class WorkFile(val path: String, val bytes: Int, val sha: String, val revision: Int)
data class WorkStep(val number: Int, val tool: String, val summary: String, val detail: String)
data class WorkSource(val id: String, val title: String, val url: String, val status: String,
    val detail: String)
data class WorkExcerpt(val source: String, val title: String, val text: String, val offset: Int,
    val next: Int, val total: Int)
data class SourceChange(val task: String, val source: String, val action: String, val revision: Int, val requestId: String)
data class WorkState(
    val tasks: List<WorkTask> = emptyList(), val more: Boolean = false, val limit: Int = 50,
    val selected: String? = null, val task: WorkTask? = null,
    val files: List<WorkFile> = emptyList(), val steps: List<WorkStep> = emptyList(),
    val sourceFiles: List<DraftAttachment> = emptyList(), val pickingSource: Boolean = false,
    val target: String = "auto", val receipts: List<WorkReceipt> = emptyList(),
    val artifacts: List<WorkArtifact> = emptyList(), val buildLimit: Int = 50, val buildMore: Boolean = false, val buildDetail: String = "",
    val title: String = "", val requirements: String = "", val model: String = "",
    val publicQuery: String = "", val followLinks: Boolean = false,
    val references: String = "", val extraReferences: String = "", val retrySources: Boolean = false,
    val sources: List<WorkSource> = emptyList(), val sourcesMore: Boolean = false, val sourceLimit: Int = 50,
    val pendingSourceChange: SourceChange? = null,
    val excerpt: WorkExcerpt? = null, val sourceLoading: Boolean = false,
    val note: String = "", val editModel: String = "", val editWeb: String = "", val editRevision: Int? = null, val busy: Boolean = false,
    val error: String? = null, val notice: String? = null,
)
fun workTask(j: JSONObject): WorkTask {
    val session = j.optJSONObject("session")
    return WorkTask(j.getString("id"), j.getString("title"), j.getString("requirements"),
        j.getString("status"), j.getInt("revision"), j.optBoolean("execution_available"),
        if (j.isNull("blocker")) null else j.optString("blocker"),
        session?.optString("model_id") ?: "", session?.optInt("step") ?: 0,
        session?.optString("summary") ?: "", j.optJSONObject("references")?.optInt("failed") ?: 0,
        j.has("references"), j.optString("build_target", "source"), j.optBoolean("code_execution_available"), j.optBoolean("source_management"), j.optJSONObject("public_research")?.let { web ->
            if(web.isNull("public_query") && !web.optBoolean("follow_links")) "" else "Public research: ${web.optString("status")}. Query: ${web.optString("public_query", "none")}. Link following: ${web.optBoolean("follow_links")}. ${if(web.isNull("error_code")) "" else web.optString("error_code") + ". Pause and retry failed sources after correcting search."}"
        } ?: "", j.optString("web_mode", "off"))
}
fun workSource(j: JSONObject): WorkSource {
    fun value(key: String) = if(j.isNull(key)) "Unavailable" else j.optString(key, "Unavailable")
    val detail = buildString {
        append("Snapshot generation: ${j.optInt("generation", 1)}\n")
        append("Requested URL: ${value("url")}\nRead URL: ${value("final_url")}\n")
        if(j.getString("status") == "retrieved") {
            append("Retrieved: ${value("retrieved_at")}\n${j.optInt("characters")} characters")
            if(j.optBoolean("text_truncated")) append(" · text was truncated")
            append("\nPublication date from page metadata (unverified): ${value("published_at")}\n")
            append("Content SHA-256: ${value("content_sha256")}\nExtracted text SHA-256: ${value("text_sha256")}")
        } else if(j.getString("status") == "failed") append("Read failed: ${value("error_code")}\nPause the task to retry failed reads.")
    }
    return WorkSource(j.getString("source_id"), j.getString("title"),
        if(j.isNull("final_url")) j.getString("url") else j.getString("final_url"), j.getString("status"), detail)
}
fun workActions(status: String): List<String> = when(status) {
    "draft" -> listOf("start", "stop")
    "running", "queued" -> listOf("pause", "stop")
    "blocked" -> listOf("resume", "pause", "stop")
    "paused" -> listOf("resume", "stop")
    "stopped" -> listOf("resume")
    else -> emptyList()
}
fun workStatus(status: String, target: String = "source") = if(status == "completed") (if(target == "source") "Draft complete" else "Build complete") else status
fun workTaskId(id: String): String {
    require(id.matches(Regex("[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"))) { "Invalid task identity" }
    return id
}

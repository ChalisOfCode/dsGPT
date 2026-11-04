package com.dsgpt.mobile

import org.json.JSONObject

data class MemoryEntry(val id: String, val title: String, val content: String,
    val revision: Int, val source: String, val updated: String)
data class MemoryProject(val id: String, val title: String)
data class MemoryUi(
    val ready: Boolean = false, val personalAllowed: Boolean = false, val projectAllowed: Boolean = false,
    val projects: List<MemoryProject> = emptyList(), val projectsMore: Boolean = false,
    val scope: String = "", val scopeTitle: String = "Personal", val query: String = "",
    val rows: List<MemoryEntry> = emptyList(), val more: Boolean = false,
    val editor: Boolean = false, val editing: MemoryEntry? = null,
    val title: String = "", val content: String = "", val deleting: MemoryEntry? = null,
    val busy: Boolean = false, val error: String? = null, val notice: String? = null,
)
fun memoryEntry(j: JSONObject) = MemoryEntry(j.getString("id"), j.getString("title"),
    j.getString("content"), j.getInt("revision"), j.getString("source"), j.getString("updated_at"))

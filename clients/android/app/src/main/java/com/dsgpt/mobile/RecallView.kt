package com.dsgpt.mobile

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import java.net.URLEncoder

private fun jsonRows(array: JSONArray) = List(array.length()) { array.getJSONObject(it) }

@Composable
fun RecallView(vm: ChatModel) {
    val coroutine = rememberCoroutineScope()
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf("") }
    var attachmentSearch by remember { mutableStateOf(false) }
    var attachmentSemantic by remember { mutableStateOf(false) }
    var chat by remember { mutableStateOf(false) }
    var owner by remember { mutableStateOf(false) }
    var projects by remember { mutableStateOf(emptyList<JSONObject>()) }
    var projectsMore by remember { mutableStateOf(false) }
    var settings by remember { mutableStateOf<JSONObject?>(null) }
    var imports by remember { mutableStateOf(emptyList<JSONObject>()) }
    var importsMore by remember { mutableStateOf(false) }
    var removing by remember { mutableStateOf<JSONObject?>(null) }
    var receipt by remember { mutableStateOf("") }
    var query by remember { mutableStateOf("") }
    var scope by remember { mutableStateOf("none") }
    var semantic by remember { mutableStateOf(false) }
    var hidden by remember { mutableStateOf(false) }
    var results by remember { mutableStateOf(emptyList<JSONObject>()) }
    var coverage by remember { mutableStateOf("") }
    val currentState by vm.state.collectAsState()
    LaunchedEffect(currentState.attachmentView?.file) {
        currentState.attachmentView?.file?.takeIf { it.removed }?.let { file ->
            results = results.filterNot { it.optString("kind") == "attachment" && it.optString("id") == file.id }
        }
    }
    fun clear() { results = emptyList(); coverage = ""; receipt = ""; error = "" }
    fun act(block: suspend () -> Unit) {
        if(busy) return
        busy = true; error = ""
        coroutine.launch {
            try { block() }
            catch(e: CancellationException) { throw e }
            catch(e: Exception) { error = e.message ?: "Request failed. Refresh before retrying." }
            finally { busy = false }
        }
    }
    suspend fun loadSettings() { settings = JSONObject(vm.recallRequest("/v1/retrieval/settings")) }
    LaunchedEffect(Unit) {
        busy = true
        try {
            val capabilities = JSONObject(vm.recallRequest("/v1/capabilities"))
            val permissions = capabilities.getJSONObject("permissions")
            attachmentSearch = capabilities.optJSONObject("attachments")?.optBoolean("keyword_search") == true
            attachmentSemantic = capabilities.optJSONObject("attachments")?.optBoolean("semantic_search") == true
            chat = permissions.optBoolean("chat"); owner = permissions.optBoolean("search_administration")
            scope = if(chat) "history" else "none"
            if(permissions.optBoolean("work")) {
                projects = jsonRows(JSONArray(vm.recallRequest("/v1/work/tasks?limit=50")))
                projectsMore = projects.size == 50
            }
            if(owner) {
                loadSettings()
                imports = jsonRows(JSONArray(vm.recallRequest("/v1/history/imports?limit=50")))
                importsMore = imports.size == 50
            }
        } catch(e: CancellationException) { throw e }
        catch(e: Exception) { error = e.message ?: "Unable to load retrieval controls" }
        finally { busy = false }
    }
    removing?.let { source -> AlertDialog(onDismissRequest = { if(!busy) removing = null },
        title = { Text("Remove imported source?") },
        text = { Text("Remove every imported version of source ${source.getString("source_id")}? Imported text is erased and reimport is blocked. Locally added turns and explicitly copied memories remain.") },
        confirmButton = { TextButton(enabled = !busy, onClick = { act {
            vm.recallRequest("/v1/history/imports/${workTaskId(source.getString("conversation_id"))}", "DELETE")
            val id = source.getString("source_id")
            imports = imports.map { if(it.getString("source_id") == id) JSONObject(it.toString()).put("removed", 1).put("source_title", JSONObject.NULL) else it }
            removing = null; clear()
        } }) { Text("Confirm source removal") } },
        dismissButton = { TextButton(enabled = !busy, onClick = { removing = null }) { Text("Keep source") } }) }
    LazyColumn(Modifier.fillMaxSize().padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item { ProjectGroupsView(currentState.connectionEpoch) { vm.recallRequest(it) } }
        item {
            Text("Search private history or one memory scope. Results are excerpts, not verified facts. Nothing is copied into memory or sent to a model automatically.")
            if(error.isNotEmpty()) Text(error, color = MaterialTheme.colorScheme.error)
            Text("Retrieval scope")
            var expanded by remember { mutableStateOf(false) }
            val scopes = (if(chat) listOf("history" to "Chat history", "personal" to "Personal memory") else emptyList()) + (if(chat && attachmentSearch) listOf("attachments" to "Saved attachments") else emptyList()) + projects.map { it.getString("id") to it.getString("title") }
            Box {
                TextButton(enabled = !busy, onClick = { expanded = true }) { Text(scopes.find { it.first == scope }?.second ?: "Choose a project") }
                DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
                    scopes.forEach { (id, title) -> DropdownMenuItem(text = { Text(title) }, onClick = { scope = id; if(id == "attachments") semantic = false; expanded = false; clear() }) }
                }
            }
            if(projectsMore) TextButton(enabled = !busy, onClick = { act {
                val rows = jsonRows(JSONArray(vm.recallRequest("/v1/work/tasks?limit=50&offset=${projects.size}")))
                projects = projects + rows; projectsMore = rows.size == 50
            } }) { Text("Load more projects") }
            Row { Checkbox(checked = semantic, enabled = !busy && (scope != "attachments" || attachmentSemantic), onCheckedChange = { semantic = it; clear() }); Text("Use local semantic retrieval") }
            if(scope in listOf("history", "attachments")) Row { Checkbox(checked = hidden, enabled = !busy, onCheckedChange = { hidden = it; clear() }); Text(if(semantic) "Include hidden chats" else "Search hidden chats only") }
            OutlinedTextField(value = query, onValueChange = { query = it.take(1000); clear() }, enabled = !busy, label = { Text("Search private content") }, modifier = Modifier.fillMaxWidth())
            Button(enabled = !busy && query.isNotBlank() && scope != "none", onClick = { act {
                clear()
                if(semantic) {
                    val body = JSONObject().put("query", query).put("kind", if(scope == "attachments") "attachment" else if(scope == "history") "history" else "memory")
                        .put("task_id", if(scope in listOf("history", "personal", "attachments")) JSONObject.NULL else scope)
                        .put("hidden", scope in listOf("history", "attachments") && hidden).put("limit", 20)
                    val response = JSONObject(vm.recallRequest("/v1/retrieval/search", "POST", body))
                    results = jsonRows(response.getJSONArray("results"))
                    coverage = response.getString("score_meaning") + "\nIndex coverage: " + response.getJSONArray("coverage").toString()
                } else {
                    val q = URLEncoder.encode(query, "UTF-8")
                    val path = if(scope == "attachments") "/v1/attachments/search?q=$q&hidden=$hidden&limit=50" else if(scope == "history") "/v1/history/search?q=$q&hidden=$hidden&limit=50" else "/v1/memories?q=$q&limit=50" + if(scope == "personal") "" else "&task_id=${workTaskId(scope)}"
                    results = jsonRows(JSONArray(vm.recallRequest(path)))
                    coverage = "Keyword search · first 50 matches. Narrow your query for additional results."
                }
            } }) { Text("Search private content") }
            if(scope == "attachments") Text("Search saved attachment text locally. Semantic indexing is a separate opt-in. Review extraction omissions and OCR errors.")
            if(coverage.isNotEmpty()) Text(coverage)
        }
        items(results) { result -> Column {
            Text(result.getString("title"), style = MaterialTheme.typography.titleMedium)
            SelectionContainer { Text(result.optString("content", result.optString("excerpt"))) }
            if(result.has("score")) Text("Similarity: ${result.getDouble("score")} · not confidence")
            if(result.optString("kind") == "attachment") {
                Text("Chat: ${result.optString("conversation_title")}")
                TextButton(enabled = !busy, onClick = { vm.showAttachment(attachmentRecords(JSONArray().put(result)).single(), result.getString("conversation_id")) }) { Text("Open saved attachment") }
            }
            if(result.has("conversation_id") && result.optString("kind") != "attachment") TextButton(enabled = !busy, onClick = { act {
                receipt = ""
                receipt = JSONObject(vm.recallRequest("/v1/conversations/${workTaskId(result.getString("conversation_id"))}/import")).toString(2)
            } }) { Text("Review import provenance") }
        } }
        if(receipt.isNotEmpty()) item { WorkDetail("Import receipt and omissions", receipt) }
        if(owner) {
            item {
                Text("Local retrieval settings", style = MaterialTheme.typography.titleLarge)
                Text("Uses the pinned English CPU embedding model. Required assets must be installed on the PC. History indexing is a separate opt-in.")
                settings?.let { config ->
                    Text("${config.getInt("chunks")} indexed chunks · " + if(config.optBoolean("loaded")) "Embedding model loaded" else "Embedding model not loaded")
                    if(!config.isNull("error_code")) Text(config.getString("error_code"))
                    WorkDetail("Index coverage", config.getJSONArray("sources").toString(2))
                    listOf("enabled" to "Enable local semantic retrieval", "history_enabled" to "Index chat history locally", "attachments_enabled" to "Index attachment text locally").forEach { (key, label) -> Row {
                        Checkbox(checked = config.optBoolean(key), enabled = !busy, onCheckedChange = { value -> act {
                            val body = JSONObject().put("revision", config.getInt("revision")).put("enabled", config.getBoolean("enabled")).put("history_enabled", config.getBoolean("history_enabled")).put("attachments_enabled", config.optBoolean("attachments_enabled")).put(key, value)
                            settings = JSONObject(vm.recallRequest("/v1/retrieval/settings", "PATCH", body)); clear()
                        } }); Text(label)
                    } }
                }
                TextButton(enabled = !busy, onClick = { act { loadSettings() } }) { Text("Refresh retrieval settings") }
                Text("Imported history", style = MaterialTheme.typography.titleLarge)
                Text("Archives are imported locally on the PC with preview and hash acceptance. Remote archive upload is not enabled.")
            }
            items(imports, key = { it.getString("conversation_id") }) { row -> Column {
                Text(if(row.isNull("source_title")) "Removed source" else row.getString("source_title"))
                Text(row.getString("imported_at"))
                TextButton(enabled = !busy, onClick = { act { receipt = JSONObject(vm.recallRequest("/v1/conversations/${workTaskId(row.getString("conversation_id"))}/import")).toString(2) } }) { Text("Review source receipt") }
                if(row.optInt("removed") == 0) TextButton(enabled = !busy, onClick = { removing = row }) { Text("Remove imported source…") }
            } }
            if(importsMore) item { TextButton(enabled = !busy, onClick = { act {
                val rows = jsonRows(JSONArray(vm.recallRequest("/v1/history/imports?limit=50&offset=${imports.size}")))
                imports = imports + rows; importsMore = rows.size == 50
            } }) { Text("Load more imports") } }
        }
    }
}

package com.dsgpt.mobile

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject

@Composable
internal fun ProjectGroupsView(connectionEpoch: Long, request: suspend (String) -> String) {
    var open by remember(connectionEpoch) { mutableStateOf(false) }
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    DisposableEffect(lifecycle, connectionEpoch) {
        val observer = LifecycleEventObserver { _, event ->
            if(event == Lifecycle.Event.ON_PAUSE || event == Lifecycle.Event.ON_STOP) open = false
        }
        lifecycle.addObserver(observer)
        onDispose { lifecycle.removeObserver(observer) }
    }
    TextButton(onClick = { open = true }) { Text("Browse project groups") }
    if(open) key(connectionEpoch) { ProjectGroupsDialog(request) { open = false } }
}

@Composable
private fun ProjectGroupsDialog(request: suspend (String) -> String, close: () -> Unit) {
    val scope = rememberCoroutineScope()
    var job by remember { mutableStateOf<Job?>(null) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf("") }
    var groups by remember { mutableStateOf(emptyList<JSONObject>()) }
    var members by remember { mutableStateOf(emptyList<JSONObject>()) }
    var offset by remember { mutableStateOf(0) }
    var selected by remember { mutableStateOf("") }
    DisposableEffect(Unit) { onDispose { job?.cancel() } }
    fun load(id: String? = null, at: Int = offset) {
        if(busy) return
        busy = true; error = ""; members = emptyList(); selected = ""
        job = scope.launch {
            try {
                val text = request(if(id == null) "/v1/project-groups?offset=$at" else "/v1/project-groups/${workTaskId(id)}")
                currentCoroutineContext().ensureActive()
                if(id == null) {
                    val rows = JSONArray(text)
                    check(rows.length() <= 50)
                    groups = List(rows.length()) { rows.getJSONObject(it) }; offset = at
                } else {
                    val data = JSONObject(text)
                    val rows = data.getJSONArray("members")
                    check(rows.length() <= 4096)
                    members = List(rows.length()) { rows.getJSONObject(it) }
                    selected = data.getJSONObject("group").getString("name")
                }
            } catch(e: CancellationException) { throw e }
            catch(_: Exception) { groups = emptyList(); members = emptyList(); error = "Group access changed or is unavailable. Refresh before retrying." }
            finally { busy = false }
        }
    }
    AlertDialog(onDismissRequest = close, title = { Text("Related projects") },
        text = { LazyColumn(Modifier.heightIn(max = 450.dp).testTag("project-groups-scroll"), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            item { Text("Read-only groups. The PC owner reviews associations. Groups do not grant source access or copy content into memory.") }
            item { TextButton(enabled = !busy, onClick = { load(at = 0) }) { Text("Refresh groups") } }
            if(error.isNotBlank()) item { Text(error, color = MaterialTheme.colorScheme.error) }
            items(groups, key = { it.getString("id") }) { group ->
                TextButton(enabled = !busy, onClick = { load(group.getString("id")) }) { Text(group.getString("name")) }
            }
            item { Row {
                TextButton(enabled = !busy && offset > 0, onClick = { load(at = (offset - 50).coerceAtLeast(0)) }) { Text("Previous groups") }
                TextButton(enabled = !busy && groups.size == 50, onClick = { load(at = offset + 50) }) { Text("Next groups") }
            } }
            if(selected.isNotEmpty()) item { Text("Linked originals · $selected") }
            items(members) { source ->
                Text(source.getString("title") + " · " + source.getString("kind") + "\nOriginal SHA256: " + source.getString("source_sha256") + "\nSource: " + source.getString("id"))
            }
            if(selected.isNotEmpty() && members.isEmpty()) item { Text("No current visible links. Changed or removed sources need owner review.") }
        } },
        confirmButton = { TextButton(onClick = close) { Text("Close groups") } })
}

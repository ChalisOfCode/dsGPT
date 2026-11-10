package com.dsgpt.mobile

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp

@Composable
fun WorkModelPicker(label: String, value: String, models: List<Model>, busy: Boolean,
    keepCurrent: Boolean = false, change: (String) -> Unit) {
    var expanded by remember { mutableStateOf(false) }
    Column {
        Text(label, style = MaterialTheme.typography.labelLarge)
        Box {
            TextButton(onClick = { expanded = true }, enabled = !busy) {
                Text(models.find { it.id == value }?.label ?: if(keepCurrent) "Keep current model" else "No configured model")
            }
            DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
                if(keepCurrent) DropdownMenuItem(text = { Text("Keep current model") }, onClick = { change(""); expanded = false })
                models.forEach { model -> DropdownMenuItem(text = { Text(model.label) }, onClick = { change(model.id); expanded = false }) }
            }
        }
    }
}

@Composable
fun WorkView(s: State, vm: ChatModel, export: (String) -> Unit, saveArtifact: (String, WorkArtifact) -> Unit, pickSource: () -> Unit) {
    val w = s.work
    val context = LocalContext.current
    var openError by remember { mutableStateOf<String?>(null) }
    w.excerpt?.let { excerpt -> AlertDialog(onDismissRequest = vm::closeWorkSource,
        title = { Text("Saved ${excerpt.source} · ${excerpt.title}") },
        text = { LazyColumn(Modifier.heightIn(max = 450.dp)) {
            item { Text("Characters ${excerpt.offset}–${excerpt.next} of ${excerpt.total}. This is saved text, not the live page.") }
            item { SelectionContainer { Text(excerpt.text) } }
            item { TextButton(onClick = { vm.readWorkSource(excerpt.source) }, enabled = !w.sourceLoading && excerpt.offset > 0) { Text("From beginning") } }
            item { TextButton(onClick = { vm.readWorkSource(excerpt.source, excerpt.next) }, enabled = !w.sourceLoading && excerpt.next < excerpt.total) { Text("Next excerpt") } }
        } }, confirmButton = { TextButton(onClick = vm::closeWorkSource) { Text("Close saved text") } }) }
    var chooseTask by remember { mutableStateOf(false) }
    var showDetails by remember { mutableStateOf(false) }
    if (chooseTask) AlertDialog(onDismissRequest = { chooseTask = false }, title = { Text("Work tasks") },
        text = { LazyColumn(Modifier.heightIn(max = 400.dp)) {
            items(w.tasks, key = { it.id }) { task ->
                TextButton(enabled = !w.busy, onClick = { vm.selectWork(task.id); chooseTask = false }) {
                    Column { Text(task.title); Text(workStatus(task.status, task.target), style = MaterialTheme.typography.bodySmall) }
                }
            }
            if(w.more) item { TextButton(onClick = vm::loadMoreWork) { Text("Load more tasks") } }
        } }, confirmButton = { TextButton(onClick = { chooseTask = false }) { Text("Close") } })
    if(w.selected == null) {
        var options by remember { mutableStateOf(false) }
        var dictating by remember { mutableStateOf(false) }
        if(options) AlertDialog(onDismissRequest = {options = false}, title = {Text("Files and task options")},
            text = { Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                TextButton(onClick = pickSource, enabled = !w.busy && !w.pickingSource && w.sourceFiles.size < 4) {Text(if(w.pickingSource) "Uploading…" else "Add APK, EXE, video or file")}
                Text("Up to four files, 256 MiB each and 512 MiB total. Tools inspect sections without filling the model context. Reselect an interrupted upload to resume.")
                w.sourceFiles.forEachIndexed { index, file -> Row {Text(file.name, Modifier.weight(1f)); TextButton(onClick = {vm.removeWorkSource(index)}) {Text("Remove")}} }
                Text("Output target")
                listOf("auto" to "Automatic from your prompt", "source" to "Source files", "files" to "Built files", "exe" to "Windows EXE", "apk" to "Android APK").forEach { (key,label) -> Row {
                    RadioButton(w.target == key, onClick = {vm.editWork("target", key)}); Text(label)
                } }
                OutlinedTextField(w.title, {vm.editWork("title", it)}, label = {Text("Task title (optional)")})
                OutlinedTextField(w.references, {vm.editWork("references", it)}, label = {Text("Public source URLs (optional)")})
                OutlinedTextField(w.publicQuery, {vm.editWork("publicQuery", it)}, label = {Text("Public search query (optional)")})
                Text("Web Auto can research throughout the task. With files it stays off unless you choose Web On. Web On allows public queries based on your task and errors; keep sensitive details out of tasks that use it. With Web off, a separate public query limits the initial search.")
            } }, confirmButton = {TextButton(onClick = {options = false}) {Text("Done")}})
        Column(Modifier.fillMaxSize()) {
            Column(Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp)) {
                TextButton(onClick = {chooseTask = true}) {Text("Recent tasks")}
                w.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                Text("What can we get done?", style = MaterialTheme.typography.headlineSmall, modifier = Modifier.padding(vertical = 24.dp))
            }
            PromptComposer(
                value = w.requirements, onValue = {vm.editWork("requirements", it)},
                hint = "Work with dsGPT", enabled = !w.busy,
                canSend = !dictating && !w.busy && !w.pickingSource && w.requirements.isNotBlank() && s.model.isNotBlank(),
                onSend = vm::createWork,
            ) {
                TextButton(onClick = {options = true}) {Text("＋ Files")}
                WebMode(if(w.sourceFiles.isNotEmpty() && s.webMode != "on") "off" else s.webMode, !w.busy, vm::webMode)
                LiveDictation(w.requirements, !w.busy, {vm.editWork("requirements", it)}, compact = true) {dictating = it}
            }
        }
        return
    }
    var updateOptions by remember(w.selected) { mutableStateOf(false) }
    var dictatingUpdate by remember(w.selected) { mutableStateOf(false) }
    val currentTask = w.task
    if(updateOptions && currentTask != null) AlertDialog(
        onDismissRequest = { updateOptions = false }, title = { Text("Task update options") },
        text = { Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            WorkModelPicker("Change Work model", w.editModel, s.models, w.busy, true) { vm.editWork("editModel", it) }
            OutlinedTextField(value = w.extraReferences, onValueChange = { vm.editWork("extraReferences", it) }, label = { Text("Add public reference URLs") }, minLines = 2, maxLines = 6, enabled = !w.busy, modifier = Modifier.fillMaxWidth())
            Text("Up to six public HTTPS URLs, one per line. New pages are read on start or resume; already saved URLs are reused.")
            if(currentTask.failedSources > 0) Row {
                Checkbox(checked = w.retrySources, onCheckedChange = { vm.editWork("retrySources", it.toString()) }, enabled = !w.busy)
                Text("Retry failed sources on start or resume")
            }
            Text("Research during this task. Web On permits public queries based on the task and its errors, including attached material.")
            Row {
                val enabled = (w.editWeb.ifBlank { currentTask.webMode }) != "off"
                Checkbox(checked = enabled, onCheckedChange = {vm.editWork("editWeb", if(it) "on" else "off")}, enabled = !w.busy)
                Text(if(enabled) "Web On" else "Web Off")
            }
            Button(onClick = {vm.reviseWork()}, enabled = !w.busy && (w.note.isNotBlank() || w.editModel.isNotBlank() || w.editWeb.isNotBlank() || w.extraReferences.isNotBlank() || w.retrySources)) { Text("Save task update") }
            TextButton(onClick = vm::clearWorkEdit, enabled = !w.busy) { Text("Clear update and reload") }
        } },
        confirmButton = { TextButton(onClick = {updateOptions = false}) {Text("Done")} },
    )
    Column(Modifier.fillMaxSize()) {
    // A replacement connection or task revision destroys the entire private view.
    if (s.connected && s.page == "work" && currentTask != null && currentTask.id == w.selected) {
        key(s.connectionEpoch, currentTask.id, currentTask.revision) {
            AccountReadView(
                grants = { vm.workAccountGrants(currentTask.id, currentTask.revision, s.connectionEpoch) },
                read = { vm.readWorkAccountGrant(currentTask.id, currentTask.revision, s.connectionEpoch, it) },
            )
        }
    }
    LazyColumn(Modifier.weight(1f).padding(horizontal = 20.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        item {
            Text("Tasks continue on your PC while you use Chat or close this app.")
            Row { TextButton(enabled = !w.busy, onClick = { vm.selectWork(null) }) { Text("New task") }
                TextButton(enabled = !w.busy, onClick = { chooseTask = true }) { Text("Work tasks") }
                TextButton(onClick = vm::refreshWorkNow) { Text("Refresh") } }
            w.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            w.notice?.let { Text(it) }
        }
        run {
            val task = w.task
            if(task == null) item { Text("Loading task…") }
            else {
                item {
                    Text(task.title, style = MaterialTheme.typography.titleLarge)
                    Text("${workStatus(task.status, task.target)} · revision ${task.revision} · ${task.step} steps")
                    Text("Model: ${s.models.find { it.id == task.model }?.label ?: task.model.ifBlank { "None selected" }}")
                    task.blocker?.let { Text(if(it == "local_vision_model_required") "Choose a locally installed Ollama vision model for attached images." else it, color = MaterialTheme.colorScheme.error) }
                    if(task.publicResearch.isNotBlank()) Text(task.publicResearch)
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        workActions(task.status).forEach { action ->
                            val label = when(action) { "start" -> if(task.target == "source") "Start drafting" else "Start build"; "resume" -> "Resume"; "pause" -> "Pause"; else -> "Stop" }
                            TextButton(onClick = { vm.transitionWork(action) }, enabled = !w.busy && (action !in listOf("start", "resume") || task.available)) { Text(label) }
                        }
                    }
                    SelectionContainer { Text(task.summary.ifBlank { "No drafting step recorded yet." }) }
                    WorkDetail("Requirements", task.requirements)
                }
                item {TextButton(onClick = {showDetails = !showDetails}) {Text(if(showDetails) "Hide source details" else "Sources and task details")}}
                if(showDetails) {
                item {
                    Text("Reference sources", style = MaterialTheme.typography.titleMedium)
                    Text("Pages are read when drafting starts or resumes. Saved snapshots are reused. Page text may be incomplete or incorrect; publication dates are unverified.")
                    Text("Refresh clears the snapshot and fetches again on start/resume. Remove excludes it from future source reads. Earlier receipts, summaries and generated files may retain copied text.")
                    w.pendingSourceChange?.let { pending ->
                        Text("${pending.action} ${pending.source}: response not confirmed.")
                        TextButton(enabled = !w.busy, onClick = { vm.changeWorkSource(pending.source, pending.action) }) { Text("Retry same source change") }
                        TextButton(enabled = !w.busy, onClick = vm::clearSourceChange) { Text("Clear source request and reload") }
                    }
                    openError?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                    if(!task.referencesAvailable) Text("Reference sources require PC backend 0.3.0.dev9 or newer.")
                    else if(w.sources.isEmpty()) Text("No reference sources added.")
                }
                items(w.sources, key = { "source:" + it.id }) { source -> Column {
                    WorkDetail("${source.id} · ${source.status} · ${source.title}", source.detail)
                    if(task.sourceManagement) Row {
                        TextButton(enabled = !w.busy && w.pendingSourceChange == null && task.status !in listOf("queued", "running", "completed"), onClick = { vm.changeWorkSource(source.id, "refresh") }) {
                            Text((if(source.status == "removed") "Restore and refresh " else "Refresh ") + source.id)
                        }
                        TextButton(enabled = !w.busy && w.pendingSourceChange == null && source.status != "removed" && task.status !in listOf("queued", "running"), onClick = { vm.changeWorkSource(source.id, "remove") }) { Text("Remove ${source.id}") }
                    }
                    if(source.status == "retrieved") Row {
                        TextButton(onClick = { vm.readWorkSource(source.id) }, enabled = !w.sourceLoading) { Text("Read saved ${source.id}") }
                        TextButton(onClick = {
                            try {
                                val url = publicSourceUrl(source.url)
                                context.startActivity(android.content.Intent(android.content.Intent.ACTION_VIEW,
                                    android.net.Uri.parse(url)).addCategory(android.content.Intent.CATEGORY_BROWSABLE))
                                openError = null
                            } catch(_: Exception) { openError = "This source could not be opened in your browser." }
                        }) { Text("Open source ${source.id}") }
                    }
                } }
                if(w.sourcesMore) item { TextButton(onClick = vm::moreWorkSources) { Text("Load more sources") } }
                }
                if(task.target != "source") {
                    if(showDetails) item {
                        Text("Build target: ${task.target}", style = MaterialTheme.typography.titleMedium)
                        Text(if(task.buildReady) "Isolated runner ready." else "Isolated runner unavailable. Check PC configuration and probe status.")
                        Text("Interrupted commands are never replayed automatically. Older artifacts may predate current source changes.")
                    }
                    if(showDetails) items(w.receipts, key = { "receipt:" + it.id }) { receipt ->
                        Column {
                            WorkDetail("Step ${receipt.step} · ${receipt.status}" + if(receipt.cleanup) " · cleanup pending" else "", "Source snapshot SHA256: ${receipt.snapshot}")
                            TextButton(onClick = { vm.readBuildReceipt(receipt.id) }, enabled = !w.busy) { Text("Read receipt and logs") }
                        }
                    }
                    if(showDetails && w.buildDetail.isNotEmpty()) item { WorkDetail("Recorded command and result", w.buildDetail) }
                    items(w.artifacts, key = { "artifact:" + it.id }) { artifact -> Column {
                        WorkDetail("${artifact.path} · ${artifact.bytes} bytes", "Execution: ${artifact.execution}\nSHA256: ${artifact.sha}")
                        TextButton(onClick = { saveArtifact(task.id, artifact) }, enabled = !w.busy) { Text("Save artifact…") }
                    } }
                    if(w.buildMore) item { TextButton(onClick = vm::moreBuildEvidence) { Text("Load more build evidence") } }
                }
                item {
                    Text("Source files (${w.files.size})", style = MaterialTheme.typography.titleMedium)
                    TextButton(onClick = { export(task.id) }, enabled = !w.busy && w.files.isNotEmpty()) { Text("Save source ZIP…") }
                }
                items(w.files, key = { "file:" + it.path }) { file -> WorkDetail("${file.path} · ${file.bytes} bytes", "Revision ${file.revision}\nSHA256 ${file.sha}") }
                if(showDetails) item { Text("Recent activity", style = MaterialTheme.typography.titleMedium); Text("Latest 100 recorded steps. Generated text is shown as data; no commands are run.") }
                if(showDetails) items(w.steps.reversed(), key = { "step:" + it.number }) { step -> WorkDetail("Step ${step.number} · ${step.tool}\n${step.summary}", step.detail) }
            }
        }
        item { Spacer(Modifier.height(24.dp)) }
    }
    if(currentTask != null && currentTask.status !in listOf("queued", "running")) key(currentTask.id) {
        PromptComposer(
            value = w.note, onValue = {vm.editWork("note", it)}, hint = "Add instructions",
            enabled = !w.busy, canSend = !w.busy && !dictatingUpdate && w.note.isNotBlank(),
            onSend = {vm.reviseWork(true)},
        ) {
            TextButton(onClick = {updateOptions = true}) {Text("Task options")}
            LiveDictation(w.note, !w.busy, {vm.editWork("note", it)}, compact = true) {dictatingUpdate = it}
        }
    }
    }
}

@Composable
fun WorkDetail(title: String, detail: String) {
    var expanded by remember(title) { mutableStateOf(false) }
    Column {
        TextButton(onClick = { expanded = !expanded }) { Text((if(expanded) "▾ " else "▸ ") + title) }
        if(expanded) SelectionContainer { Text(detail, style = MaterialTheme.typography.bodySmall) }
        HorizontalDivider()
    }
}


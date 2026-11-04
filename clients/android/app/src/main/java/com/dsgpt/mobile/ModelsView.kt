package com.dsgpt.mobile

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import java.util.Locale

private fun modelSize(bytes: Long) = String.format(Locale.ROOT, "%.1f MiB", bytes / 1048576.0)

@Composable
private fun ModelChoice(label: String, value: String, choices: List<Pair<String, String>>, enabled: Boolean, select: (String) -> Unit) {
    var open by remember { mutableStateOf(false) }
    TextButton(onClick = { open = true }, enabled = enabled) { Text("$label: ${choices.find { it.first == value }?.second ?: "Choose…"}") }
    if(open) AlertDialog(onDismissRequest = { open = false }, title = { Text(label) },
        text = { LazyColumn(Modifier.heightIn(max = 350.dp)) {
            if(choices.isEmpty()) item { Text("No verified choices available. Complete the downloads and runtime installation first.") }
            items(choices, key = { it.first }) { choice -> TextButton(onClick = { select(choice.first); open = false }) { Text(choice.second) } }
        } }, confirmButton = { TextButton(onClick = { open = false }) { Text("Close") } })
}

@Composable
private fun ModelField(label: String, value: String, enabled: Boolean, numeric: Boolean = false, change: (String) -> Unit) {
    OutlinedTextField(value = value, onValueChange = change, label = { Text(label) }, enabled = enabled,
        modifier = Modifier.fillMaxWidth(), singleLine = true,
        keyboardOptions = KeyboardOptions(keyboardType = if(numeric) KeyboardType.Number else KeyboardType.Text))
}

@Composable
fun ModelsView(m: ModelsUi, manager: ModelManager) {
    val context = LocalContext.current
    var openError by remember { mutableStateOf<String?>(null) }
    m.removal?.let { removal -> AlertDialog(onDismissRequest = { manager.removal(null) },
        title = { Text(removal.title) }, text = { Text(removal.detail) },
        confirmButton = { TextButton(onClick = manager::confirmRemoval, enabled = !m.busy) { Text("Confirm removal") } },
        dismissButton = { TextButton(onClick = { manager.removal(null) }, enabled = !m.busy) { Text("Keep it") } }) }
    LazyColumn(Modifier.fillMaxSize().padding(horizontal = 20.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        item {
            Text("Setup adds standard Qwen 3.5 models automatically and keeps your existing altered model. 9B favors speed; 27B uses system RAM too and is slower on a 12 GB GPU. -A means abliterated; -NA means unaltered. The controls below are optional manual model management.")
            TextButton(onClick = manager::refreshNow, enabled = !m.busy) { Text("Refresh models") }
            m.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            openError?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            m.notice?.let { Text(it) }
            if(m.busy) Text("Applying change on your PC… Verification may take a while.")
            if(m.allowed == null && m.error == null) Text("Checking device permissions…")
            if(m.allowed == false) Text("This phone cannot manage models. On the desktop, generate a new pairing code with “Allow model management”, then pair this phone again.")
        }
        if(m.allowed == true) {
            item { ModelChoice("View", m.tab, listOf("library" to "Model Library", "runtimes" to "Runtimes", "registered" to "Available models", "add" to "Add model"), true, manager::tab) }
            when(m.tab) {
                "library" -> {
                    item { Text("The current models are integration fixtures. Target GPU benchmarks and final recommendations are still pending.") }
                    items(m.assets, key = { it.id }) { asset ->
                        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            Text(asset.name, style = MaterialTheme.typography.titleMedium)
                            Text("${if(asset.kind == "model") "Model weights" else "Runtime archive"} · ${modelSize(asset.size)} · ${asset.license}")
                            Text(asset.purpose)
                            SelectionContainer { Text(asset.source, style = MaterialTheme.typography.bodySmall) }
                            TextButton(onClick = {
                                try { context.startActivity(android.content.Intent(android.content.Intent.ACTION_VIEW,
                                    android.net.Uri.parse(publicSourceUrl(asset.source))).addCategory(android.content.Intent.CATEGORY_BROWSABLE)); openError = null }
                                catch(_: Exception) { openError = "The publisher page could not be opened." }
                            }) { Text("Open publisher page") }
                            SelectionContainer { Text("SHA-256: ${asset.sha256}", style = MaterialTheme.typography.bodySmall) }
                            val d = m.downloads.find { it.asset == asset.id }
                            if(d == null) Button(onClick = { manager.download(asset.id) }, enabled = !m.busy) { Text("Download asset") }
                            else {
                                Text("${d.status} · ${modelSize(d.downloaded)} / ${modelSize(d.total)}${d.error?.let { " · $it" } ?: ""}")
                                LinearProgressIndicator(progress = { if(d.total > 0) (d.downloaded.toDouble() / d.total).toFloat().coerceIn(0f, 1f) else 0f }, modifier = Modifier.fillMaxWidth())
                                if(d.pausable) TextButton(onClick = { manager.downloadAction(d.id, "pause") }, enabled = !m.busy) { Text("Pause download") }
                                if(d.resumable) TextButton(onClick = { manager.downloadAction(d.id, "resume") }, enabled = !m.busy) { Text("Resume download") }
                                if(d.cancellable) TextButton(onClick = { manager.downloadAction(d.id, "cancel") }, enabled = !m.busy) { Text("Cancel download") }
                                if(d.removable) TextButton(onClick = { manager.removal(ModelRemoval("Remove ${asset.name}?", "Deletes this dsGPT-owned download, including partial files. Forget attached models and remove dependent runtimes first. Existing Ollama and Prometheus files are preserved.", "/v1/downloads/${d.id}")) }, enabled = !m.busy) { Text("Remove download…") }
                            }
                            HorizontalDivider()
                        }
                    }
                }
                "runtimes" -> {
                    item {
                        Text("Managed runtime: ${m.runtimeState}${m.activeModel?.let { " · $it" } ?: ""}${if(m.runtimeBusy) " · busy" else ""}${m.runtimeError?.let { " · $it" } ?: ""}")
                        TextButton(onClick = { manager.mutate("/v1/runtime/unload", notice = "Managed model unloaded. Existing external runtimes are unchanged.") }, enabled = !m.busy && !m.runtimeBusy && m.runtimeState == "loaded") { Text("Unload managed model") }
                    }
                    items(m.runtimes, key = { it.id }) { runtime ->
                        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            Text(runtime.id, style = MaterialTheme.typography.titleMedium)
                            Text("${runtime.platform} · ${if(runtime.supported) "Matches backend platform" else "For a different backend platform"} · ${if(runtime.installed) "Installed" else "Not installed"}")
                            Text("Required downloads: " + runtime.assets.joinToString { "$it (${if(m.downloaded(it)) "verified" else "needed"})" })
                            if(runtime.installed) TextButton(onClick = { manager.removal(ModelRemoval("Remove ${runtime.id}?", "Removes this dsGPT-owned runtime installation. Forget its attached models first. Downloaded archives remain available.", "/v1/runtimes/${runtime.id}")) }, enabled = !m.busy && !m.runtimeBusy) { Text("Remove runtime…") }
                            else Button(onClick = { manager.mutate("/v1/runtimes/${runtime.id}/install", notice = "Runtime installed and verified. Add a downloaded model next.") }, enabled = !m.busy && !m.runtimeBusy && runtime.supported && runtime.assets.all(m::downloaded)) { Text("Install runtime") }
                            HorizontalDivider()
                        }
                    }
                }
                "registered" -> {
                    if(m.models.isEmpty()) item { Text("No models configured. Start in Model Library or register an existing local runtime.") }
                    items(m.models, key = { it.id }) { model ->
                        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            Text(model.label, style = MaterialTheme.typography.titleMedium)
                            Text("${model.id} · ${model.runtime} · ${if(model.managed) "Managed by dsGPT" else "Existing local runtime"}")
                            Text("Context ${model.context} · maximum output ${model.output} · performance not benchmarked")
                            if(model.configurationOwned) Text("Defined in the backend configuration file.")
                            else TextButton(onClick = { manager.removal(ModelRemoval("Forget ${model.label}?", "Removes this registration from Chat and Work. Model files remain. Active requests must finish or pause first.", "/v1/models/${model.id}")) }, enabled = !m.busy && !m.runtimeBusy) { Text("Forget model…") }
                            HorizontalDivider()
                        }
                    }
                }
                "add" -> item {
                    val f = m.form
                    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                        Row { Checkbox(f.external, { value -> manager.edit { it.copy(external = value) } }, enabled = !m.busy); Text("Use an existing local Ollama or llama.cpp runtime") }
                        ModelField("Model ID", f.id, !m.busy) { value -> manager.edit { it.copy(id = value.take(100)) } }
                        ModelField("Display name", f.name, !m.busy) { value -> manager.edit { it.copy(name = value.take(200)) } }
                        if(f.external) {
                            Text("The runtime must already run on the backend PC. Registration verifies local metadata and leaves weights unchanged.")
                            ModelChoice("Runtime type", f.engine, listOf("ollama" to "Ollama", "llama.cpp" to "llama.cpp"), !m.busy) { value -> manager.edit { it.copy(engine = value, endpoint = if(value == "ollama") "http://127.0.0.1:11434" else "http://127.0.0.1:8080") } }
                            ModelField("Local runtime address", f.endpoint, !m.busy) { value -> manager.edit { it.copy(endpoint = value.take(100)) } }
                            ModelField("Runtime model identifier", f.runtimeModel, !m.busy) { value -> manager.edit { it.copy(runtimeModel = value.take(200)) } }
                            Row { Checkbox(f.abliterated, { value -> manager.edit { it.copy(abliterated = value) } }, enabled = !m.busy); Text("Label this model as abliterated") }
                        } else {
                            ModelChoice("Downloaded model", f.asset, m.assets.filter { it.kind == "model" && m.downloaded(it.id) }.map { it.id to it.name }, !m.busy) { value -> manager.edit { it.copy(asset = value) } }
                            ModelChoice("Installed runtime", f.runtime, m.runtimes.filter { it.supported && it.installed }.map { it.id to it.id }, !m.busy) { value -> manager.edit { it.copy(runtime = value, gpu = "0") } }
                            ModelField("GPU layers", f.gpu, !m.busy && f.runtime.endsWith("windows-cuda12"), true) { value -> manager.edit { it.copy(gpu = value.take(3)) } }
                            Text("0 uses CPU. CUDA offload and context sizes still need testing on your GPU.")
                        }
                        ModelField("Context tokens", f.context, !m.busy, true) { value -> manager.edit { it.copy(context = value.take(6)) } }
                        ModelField("Maximum output tokens", f.output, !m.busy, true) { value -> manager.edit { it.copy(output = value.take(6)) } }
                        Text("Output must be smaller than context. These starting values are unbenchmarked.")
                        Button(onClick = manager::register, enabled = !m.busy && !m.runtimeBusy && m.canRegister()) { Text("Add configured model") }
                    }
                }
            }
        }
        item { Spacer(Modifier.height(24.dp)) }
    }
}

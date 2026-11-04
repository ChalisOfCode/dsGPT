package com.dsgpt.mobile

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

@Composable
fun MemoryView(s: State, vm: ChatModel, export: (String) -> Unit) {
    val m = s.memory
    var scopePicker by remember { mutableStateOf(false) }
    val allowed = m.ready && if(m.scope.isBlank()) m.personalAllowed else m.projectAllowed
    if(scopePicker) AlertDialog(onDismissRequest = { scopePicker = false }, title = { Text("Memory scope") },
        text = { LazyColumn(Modifier.heightIn(max = 400.dp)) {
            item { TextButton(onClick = { vm.selectMemoryScope("", "Personal"); scopePicker = false }, enabled = m.personalAllowed) { Text("Personal") } }
            items(m.projects, key = { it.id }) { project -> TextButton(onClick = { vm.selectMemoryScope(project.id, project.title); scopePicker = false }) { Text(project.title) } }
            if(m.projectsMore) item { TextButton(onClick = vm::moreMemoryProjects) { Text("Load more projects") } }
        } }, confirmButton = { TextButton(onClick = { scopePicker = false }) { Text("Close") } })
    m.deleting?.let { row -> AlertDialog(onDismissRequest = { vm.confirmMemoryDelete(null) },
        title = { Text("Delete “${row.title}”?") }, text = { Text("This removes it from future retrieval. Existing conversations and backups remain.") },
        confirmButton = { TextButton(onClick = vm::deleteMemory, enabled = !m.busy) { Text("Delete memory") } },
        dismissButton = { TextButton(onClick = { vm.confirmMemoryDelete(null) }, enabled = !m.busy) { Text("Cancel") } }) }
    LazyColumn(Modifier.fillMaxSize().padding(horizontal = 20.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        item {
            Text("Saved on your PC. Personal memories support Chat; project memories support that Work task. Retrieval currently uses matching words.")
            TextButton(onClick = { scopePicker = true }, enabled = m.ready && !m.busy && !m.editor) { Text("Scope: ${m.scopeTitle}") }
            OutlinedTextField(value = m.query, onValueChange = vm::queryMemory, label = { Text("Search memories") }, modifier = Modifier.fillMaxWidth(), enabled = !m.editor)
            Row {
                TextButton(onClick = vm::refreshMemoryPageNow, enabled = !m.busy) { Text("Refresh") }
                TextButton(onClick = { vm.editMemory(null) }, enabled = allowed && !m.busy && !m.editor) { Text("Add memory") }
            }
            TextButton(onClick = { export(m.scope) }, enabled = allowed && !m.busy && !m.editor) { Text("Export scope JSON…") }
            m.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            m.notice?.let { Text(it) }
            if(m.ready && !allowed) Text("This device lacks permission for this memory scope.")
        }
        if(m.editor) item {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text(if(m.editing == null) "Add memory" else "Edit memory", style = MaterialTheme.typography.titleLarge)
                OutlinedTextField(value = m.title, onValueChange = { vm.changeMemory("title", it) }, label = { Text("Memory title") }, modifier = Modifier.fillMaxWidth(), enabled = !m.busy)
                OutlinedTextField(value = m.content, onValueChange = { vm.changeMemory("content", it) }, label = { Text("Memory content") }, modifier = Modifier.fillMaxWidth(), minLines = 4, maxLines = 10, enabled = !m.busy)
                Row {
                    Button(onClick = vm::saveMemory, enabled = !m.busy && m.title.isNotBlank() && m.content.isNotBlank()) { Text("Save memory") }
                    TextButton(onClick = vm::cancelMemoryEdit, enabled = !m.busy) { Text("Cancel editing") }
                }
                HorizontalDivider()
            }
        }
        items(m.rows, key = { it.id }) { row ->
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(row.title, style = MaterialTheme.typography.titleMedium)
                SelectionContainer { Text(row.content) }
                Text("${if(row.source == "agent") "Saved by Work" else "Saved by you"} · revision ${row.revision}\n${row.updated}", style = MaterialTheme.typography.bodySmall)
                Row {
                    TextButton(onClick = { vm.editMemory(row) }, enabled = !m.busy && !m.editor) { Text("Edit") }
                    TextButton(onClick = { vm.confirmMemoryDelete(row) }, enabled = !m.busy && !m.editor) { Text("Delete") }
                }
                HorizontalDivider()
            }
        }
        if(m.rows.isEmpty() && m.ready) item { Text("No memories found in this scope.") }
        if(m.more) item { TextButton(onClick = { vm.refreshMemoryNow(true) }, enabled = !m.busy && !m.editor) { Text("Load more memories") } }
        item { Spacer(Modifier.height(24.dp)) }
    }
}

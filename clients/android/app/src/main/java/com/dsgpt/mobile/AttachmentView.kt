package com.dsgpt.mobile

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

@Composable
fun AttachmentDialog(page: AttachmentPage, vm: ChatModel, save: () -> Unit) {
    var removing by remember(page.file.id) { mutableStateOf(false) }
    AlertDialog(onDismissRequest = vm::closeAttachment,
        title = { Text(page.file.name) },
        text = { Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("${page.file.bytes} original bytes\nSaved: ${page.file.created}")
            page.file.documentNotice?.let { Text(it) }
            SelectionContainer { Text("SHA-256 ${page.file.sha256}") }
            Text("This conversation's file is used only for local Chat context. Public Research does not use it.")
            page.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            page.notice?.let { Text(it) }
            if(page.loading) Text("Loading…")
            if(page.file.removed) Text("The stored file body was removed.") else {
                page.text?.let { SelectionContainer { Text(it.ifEmpty { "(Empty file)" }) }
                    Text("Characters ${page.offset}–${page.offset + it.codePointCount(0, it.length)} of ${page.total}") }
                Row { TextButton(onClick = { vm.readAttachmentPage(0) }, enabled = !page.loading) { Text("First excerpt") }
                    TextButton(onClick = { page.next?.let(vm::readAttachmentPage) }, enabled = page.next != null && !page.loading) { Text("Next excerpt") } }
                TextButton(onClick = save, enabled = !page.loading) { Text("Save attached file…") }
                TextButton(onClick = { removing = true }, enabled = !page.loading) { Text("Remove stored file…") }
            }
        } }, confirmButton = { TextButton(onClick = vm::closeAttachment) { Text("Close") } })
    if(removing) AlertDialog(onDismissRequest = { removing = false }, title = { Text("Remove stored attachment?") },
        text = { Text("Remove ${page.file.name} from future local Chat context? Message text, replies and older backups remain. Accepted replies must finish or be cancelled first.") },
        confirmButton = { TextButton(onClick = { removing = false; vm.removeStoredAttachment() }) { Text("Confirm removal") } },
        dismissButton = { TextButton(onClick = { removing = false }) { Text("Keep file") } })
}

package com.dsgpt.mobile

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** The editor owns space before optional content; only its text scrolls as a draft grows. */
@Composable
fun PromptComposer(
    value: String,
    onValue: (String) -> Unit,
    hint: String,
    enabled: Boolean,
    canSend: Boolean,
    onSend: () -> Unit,
    stop: (() -> Unit)? = null,
    tools: @Composable RowScope.() -> Unit,
) {
    BoxWithConstraints(Modifier.fillMaxWidth().testTag("prompt-composer")) {
        // Leave room for the toolbar, including a one-line dictation status.
        // This adapts to a tall keyboard, split screen and enlarged system text.
        val editorHeight = (maxHeight - 96.dp).coerceIn(56.dp, 160.dp)
        Column(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp)) {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.Bottom) {
                OutlinedTextField(
                    value = value,
                    onValueChange = onValue,
                    placeholder = { Text(hint) },
                    enabled = enabled,
                    textStyle = MaterialTheme.typography.bodyLarge,
                    shape = RoundedCornerShape(24.dp),
                    minLines = 1,
                    maxLines = 5,
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedTextColor = MaterialTheme.colorScheme.onSurface,
                        unfocusedTextColor = MaterialTheme.colorScheme.onSurface,
                        cursorColor = MaterialTheme.colorScheme.primary,
                        focusedContainerColor = MaterialTheme.colorScheme.surface,
                        unfocusedContainerColor = MaterialTheme.colorScheme.surface,
                    ),
                    modifier = Modifier.weight(1f)
                        .heightIn(min = 56.dp, max = editorHeight)
                        .testTag("prompt-input")
                        .semantics { contentDescription = hint },
                )
                Spacer(Modifier.width(8.dp))
                FilledIconButton(
                    onClick = { if (stop != null) stop() else onSend() },
                    enabled = stop != null || canSend,
                    modifier = Modifier.size(48.dp).testTag("prompt-send")
                        .semantics { contentDescription = if (stop != null) "Stop response" else "Send prompt" },
                ) { Text(if (stop != null) "■" else "↑", fontSize = 24.sp) }
            }
            Row(
                Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                verticalAlignment = Alignment.CenterVertically,
                content = tools,
            )
        }
    }
}

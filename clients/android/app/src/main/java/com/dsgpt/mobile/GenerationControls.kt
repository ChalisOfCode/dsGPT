package com.dsgpt.mobile

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp

@Composable
fun GenerationBar(s: State, vm: ChatModel) {
    var modelMenu by remember { mutableStateOf(false) }
    var effortMenu by remember { mutableStateOf(false) }
    LaunchedEffect(s.model, s.origin) { vm.loadThinking() }
    Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp), horizontalArrangement = Arrangement.End,
        verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.weight(1f, fill = false)) {
            TextButton(onClick = { modelMenu = true }, enabled = !s.busy) {
                Text(s.models.find { it.id == s.model }?.label ?: "Choose model", maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            DropdownMenu(modelMenu, { modelMenu = false }) {
                s.models.forEach { model -> DropdownMenuItem(text = { Text(model.label) }, onClick = {vm.model(model.id); modelMenu = false}) }
            }
        }
        Box {
            TextButton(onClick = { effortMenu = true }, enabled = !s.busy && s.thinkingChoices.size > 1) {
                Text(s.thinkingChoices.find { it.first == s.effort }?.second ?: "Model default")
            }
            DropdownMenu(effortMenu, { effortMenu = false }) {
                s.thinkingChoices.forEach { choice -> DropdownMenuItem(text = {Text(choice.second)}, onClick = {vm.effort(choice.first); effortMenu = false}) }
            }
        }
    }
}

@Composable
fun WebMode(value: String, enabled: Boolean = true, change: (String) -> Unit) {
    var menu by remember { mutableStateOf(false) }
    Box {
        TextButton(onClick = { menu = true }, enabled = enabled) { Text("Web · " + value.replaceFirstChar { it.uppercase() }) }
        DropdownMenu(menu, {menu = false}) {
            listOf("auto", "on", "off").forEach { mode -> DropdownMenuItem(text = {Text(mode.replaceFirstChar { it.uppercase() })}, onClick = {change(mode); menu = false}) }
        }
    }
}

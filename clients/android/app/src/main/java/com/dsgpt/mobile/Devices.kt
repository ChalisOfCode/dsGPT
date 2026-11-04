package com.dsgpt.mobile

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

data class DeviceIdentity(val id: String, val name: String, val role: String, val created: String, val scopes: List<String>)
data class DeviceUi(val identity: DeviceIdentity? = null, val loading: Boolean = false, val error: String? = null)
fun devicePermissions(scopes: List<String>) = listOf(
    "Chat and personal memory" to scopes.contains("chat"),
    "Work and project memory" to scopes.contains("work"),
    "Diagnostics" to scopes.contains("diagnostics"),
    "Model management" to (scopes.contains("models") || scopes.contains("admin")),
    "Device administration" to scopes.contains("admin"),
)

@Composable
fun DeviceView(s: State, vm: ChatModel) {
    val d = s.device
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Text("This phone's access", style = MaterialTheme.typography.headlineSmall)
        Text("These permissions belong to the saved credential for this PC.")
        TextButton(onClick = vm::refreshDeviceNow, enabled = !d.loading) { Text("Refresh permissions") }
        if(d.loading) Text("Checking this phone's credential…")
        d.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        d.identity?.let { identity ->
            Text(identity.name, style = MaterialTheme.typography.titleMedium)
            SelectionContainer { Text("Device ID: ${identity.id}") }
            Text("Paired: ${identity.created}")
            devicePermissions(identity.scopes).forEach { (name, allowed) -> Text("$name: ${if(allowed) "Allowed" else "Not allowed"}") }
            HorizontalDivider()
            Text("To grant model management, generate a new code on the desktop with “Allow model management”, then pair again. Re-pairing creates a new credential; revoke the old device ID separately in Connected Devices.")
        }
        Text("The desktop owner can revoke this credential in Settings → Connected Devices. Revocation blocks new requests; already accepted replies, Work and downloads may finish on the PC.")
        Text("Disconnect removes the saved connection from this phone. It does not revoke the server credential or delete content on your PC.")
        TextButton(onClick = vm::disconnect, enabled = !d.loading) { Text("Disconnect this phone") }
    }
}

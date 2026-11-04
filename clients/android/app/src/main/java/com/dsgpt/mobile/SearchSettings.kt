package com.dsgpt.mobile

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

data class SearchTest(val status: String, val checked: String, val results: Int, val failures: Int, val error: String?)
data class SearchStatus(val origin: String?, val owned: Boolean, val checking: Boolean, val last: SearchTest?)
data class SearchUi(val status: SearchStatus? = null, val loading: Boolean = false, val error: String? = null)

@Composable
fun SearchSettingsView(s: State, vm: ChatModel) {
    val ui = s.searchSetup
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Text("Web search on your PC", style = MaterialTheme.typography.headlineSmall)
        Text("The desktop owner installs or connects a local SearXNG service in Settings → Web search. This phone can view its configuration and last test.")
        TextButton(onClick = vm::refreshSearchNow, enabled = !ui.loading) { Text("Refresh search status") }
        if(ui.loading) Text("Refreshing status…")
        ui.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        ui.status?.let { status ->
            if(ui.error != null) Text("Showing the last known status.")
            SelectionContainer { Text(status.origin?.let { "PC search address: $it" } ?: "Web search is not configured.") }
            if(status.owned) Text("This address is controlled by the PC backend configuration file.")
            if(status.checking) Text("A search test is in progress on the PC.")
            Text("Last test", style = MaterialTheme.typography.titleMedium)
            status.last?.let { last ->
                Text(when(last.status) {
                    "passed" -> "Test returned results"
                    "partial" -> "Some search engines did not respond"
                    "empty" -> "Test returned no results"
                    "failed" -> "Test failed"
                    else -> "Unknown test result"
                })
                Text("Checked: ${last.checked}\n${last.results} public results · ${last.failures} engine failures")
                last.error?.let { Text("$it. Ask the desktop owner to check the service and JSON output.") }
            } ?: Text("No test is recorded for this address and revision.")
        }
        Text("Refreshing this page sends no search query. The owner's test sends “SearXNG documentation” through the configured service, without chat history or saved memory. A past test does not guarantee availability or factual accuracy.")
        Text("Research is opt-in for each message. Explicit public source URLs still work without web search. The phone accesses search through your PC; it does not run SearXNG itself.")
    }
}

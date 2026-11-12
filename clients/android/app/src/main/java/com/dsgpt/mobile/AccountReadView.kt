package com.dsgpt.mobile

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.DialogProperties
import androidx.compose.ui.window.SecureFlagPolicy
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.launch

@Composable
internal fun AccountReadView(grants: suspend () -> List<AccountReadGrant>,
    read: suspend (String) -> AccountReadPage) {
    var open by remember { mutableStateOf(false) }
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    DisposableEffect(lifecycle) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_PAUSE || event == Lifecycle.Event.ON_STOP) open = false
        }
        lifecycle.addObserver(observer)
        onDispose { lifecycle.removeObserver(observer) }
    }
    TextButton(onClick = { open = true }) { Text("Private account pages") }
    if (open) PrivateAccountDialog(grants, read) { open = false }
}

@Composable
private fun PrivateAccountDialog(loadGrants: suspend () -> List<AccountReadGrant>,
    read: suspend (String) -> AccountReadPage, close: () -> Unit) {
    val scope = rememberCoroutineScope()
    var job by remember { mutableStateOf<Job?>(null) }
    var grants by remember { mutableStateOf<List<AccountReadGrant>?>(null) }
    var page by remember { mutableStateOf<AccountReadPage?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    var generation by remember { mutableStateOf(0L) }
    // No rememberSaveable, ViewModel, clipboard, share or disk storage for page data.
    DisposableEffect(Unit) { onDispose { job?.cancel() } }
    LaunchedEffect(Unit) { delay(5 * 60_000L); close() }
    LaunchedEffect(grants) {
        val expiry = grants?.minOfOrNull { it.expiresAt } ?: return@LaunchedEffect
        delay(((expiry * 1000 - System.currentTimeMillis()).toLong()).coerceAtLeast(0))
        generation++; job?.cancel(); busy = false; page = null; grants = null
        error = "Permission expired. Check private account grants again."
    }
    fun load(grant: AccountReadGrant? = null) {
        if (busy) return
        val own = ++generation
        busy = true; page = null; error = null
        job = scope.launch {
            try {
                if (grant == null) {
                    val result = loadGrants()
                    currentCoroutineContext().ensureActive()
                    grants = result
                } else {
                    check(grant.expiresAt * 1000 > System.currentTimeMillis())
                    val result = read(grant.id)
                    currentCoroutineContext().ensureActive()
                    check(grant.expiresAt * 1000 > System.currentTimeMillis())
                    page = result
                }
            } catch (e: CancellationException) { throw e }
            catch (_: Exception) {
                grants = null; page = null
                error = "Account access is unavailable. Ask the owner to review the task and device permission, then check again."
            } finally { if (own == generation) busy = false }
        }
    }
    AlertDialog(onDismissRequest = close,
        properties = DialogProperties(securePolicy = SecureFlagPolicy.SecureOn),
        title = { Text("Private account pages") },
        text = { LazyColumn(Modifier.heightIn(max = 450.dp).testTag("private-account-scroll"), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            item { Text("The PC owner must grant this phone access to the current task and saved account page. Page text stays in this view; it is not sent to the model or saved with the task.") }
            item { TextButton(onClick = { load() }, enabled = !busy) { Text("Check private account grants") } }
            if (busy) item { Text("Checking private account access…") }
            error?.let { message -> item { Text(message, color = MaterialTheme.colorScheme.error) } }
            if (grants?.isEmpty() == true) item { Text("No current account grants for this task and device.") }
            items(grants.orEmpty(), key = { it.id }) { grant ->
                Column {
                    Text(grant.label)
                    Text(grant.origin + grant.path)
                    TextButton(onClick = { load(grant) }, enabled = !busy) { Text("Read approved page") }
                }
            }
            page?.let { value ->
                item { Text(value.text) }
                if (value.truncated) item { Text("Only the beginning of the page is shown.") }
            }
        } },
        confirmButton = { TextButton(onClick = close) { Text("Close private account view") } })
}

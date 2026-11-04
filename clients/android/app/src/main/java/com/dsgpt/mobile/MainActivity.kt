package com.dsgpt.mobile

import android.content.Context
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.gestures.scrollBy
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.contentDescription
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.repeatOnLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    private val frameListener = android.view.Window.OnFrameMetricsAvailableListener { _, metrics, dropped ->
        MobileTelemetry.frame(metrics.getMetric(android.view.FrameMetrics.TOTAL_DURATION), dropped)
    }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addOnFrameMetricsAvailableListener(frameListener, android.os.Handler(mainLooper))
        enableEdgeToEdge()
        setContent {
            MaterialTheme(
                colorScheme =
                    darkColorScheme(
                        primary = Color(0xffececec),
                        onPrimary = Color(0xff212121),
                        secondary = Color(0xffc6c6c6),
                        background = Color(0xff212121),
                        surface = Color(0xff2f2f2f),
                    )
            ) {
                Surface(Modifier.fillMaxSize()) { MobileApp() }
            }
        }
    }

    override fun onStart() { super.onStart(); MobileTelemetry.record(DiagnosticEvent.FOREGROUND) }
    override fun onStop() {
        if (!isChangingConfigurations) MobileTelemetry.record(DiagnosticEvent.BACKGROUND)
        super.onStop()
    }
    override fun onDestroy() { window.removeOnFrameMetricsAvailableListener(frameListener); super.onDestroy() }
}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun MobileApp(vm: ChatModel = viewModel()) {
    val s by vm.state.collectAsStateWithLifecycle()
    val models by vm.modelManagement.state.collectAsStateWithLifecycle()
    val modelsLifecycle = LocalLifecycleOwner.current
    LaunchedEffect(s.page, s.connected) {
        if(s.connected && s.page == "models") modelsLifecycle.lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) { vm.modelManagement.observe() }
    }
    val export =
        rememberLauncherForActivityResult(
            ActivityResultContracts.CreateDocument("application/zip")
        ) { uri ->
            if (uri != null) vm.saveExport(uri)
        }
    var attachmentSaveChat by rememberSaveable { mutableStateOf("") }
    var attachmentSaveId by rememberSaveable { mutableStateOf("") }
    var attachmentSaveSession by rememberSaveable { mutableStateOf("") }
    val attachmentExport = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/octet-stream")) { uri ->
        if(uri != null && attachmentSaveId.isNotBlank()) vm.saveAttachment(attachmentSaveChat, attachmentSaveId, attachmentSaveSession, uri)
        attachmentSaveId = ""
    }
    s.attachmentView?.let { page -> AttachmentDialog(page, vm) {
        attachmentSaveChat = page.chatId; attachmentSaveId = page.file.id; attachmentSaveSession = s.attachmentSession; attachmentExport.launch(page.file.name)
    } }
    val lifecycle = LocalLifecycleOwner.current
    LaunchedEffect(s.page, s.connected) {
        if(s.connected && s.page in listOf("chat", "chats", "search")) lifecycle.lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) { vm.observeSearchReadiness() }
    }
    LaunchedEffect(s.page, s.connected) {
        if(s.connected && s.page == "devices") lifecycle.lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) { vm.refreshDevice() }
    }
    var workSourceOrigin by rememberSaveable { mutableStateOf("") }
    val workSourcePicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if(uri != null) vm.addWorkSource(uri, workSourceOrigin)
        workSourceOrigin = ""
    }
    var artifactTask by rememberSaveable { mutableStateOf("") }
    var artifactOrigin by rememberSaveable { mutableStateOf("") }
    var artifactMetadata by rememberSaveable { mutableStateOf("") }
    val artifactExport = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/octet-stream")) { uri ->
        if(uri != null && artifactMetadata.isNotEmpty()) {
            val a = org.json.JSONObject(artifactMetadata)
            vm.saveWorkArtifact(artifactTask, WorkArtifact(a.getString("id"), a.getString("execution"), a.getString("path"), a.getInt("bytes"), a.getString("sha")), artifactOrigin, uri)
        }
        artifactMetadata = ""
    }
    var workExportTask by rememberSaveable { mutableStateOf("") }
    var memoryExportScope by rememberSaveable { mutableStateOf("") }
    var memoryExportOrigin by rememberSaveable { mutableStateOf("") }
    val memoryExport = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/json")) { uri ->
        if(uri != null && memoryExportOrigin.isNotBlank()) vm.saveMemoryExport(memoryExportScope, memoryExportOrigin, uri)
        memoryExportOrigin = ""
    }
    LaunchedEffect(s.page, s.connected) {
        if(s.connected && s.page == "memory") lifecycle.lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) { vm.refreshMemoryPage() }
    }
    var workExportOrigin by rememberSaveable { mutableStateOf("") }
    val workExport = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/zip")) { uri ->
        if(uri != null && workExportTask.isNotBlank()) vm.saveWorkExport(workExportTask, workExportOrigin, uri)
        workExportTask = ""
    }
    DisposableEffect(lifecycle,vm) {
        val listener=LifecycleEventObserver {_,event->if(event==Lifecycle.Event.ON_RESUME)vm.restoreUpdatedConnection()}
        lifecycle.lifecycle.addObserver(listener)
        onDispose{lifecycle.lifecycle.removeObserver(listener)}
    }
    LaunchedEffect(s.connected, s.origin) {
        if(s.connected) lifecycle.lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) {vm.observeConnection()}
    }
    LaunchedEffect(s.page, s.connected, s.work.selected) {
        if(s.connected && s.page == "work") lifecycle.lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) { vm.observeWork() }
    }
    LaunchedEffect(s.selected, s.page, s.connected) {
        val id = s.selected
        if (s.connected && s.page == "chat" && id != null) {
            lifecycle.lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) { vm.observeChat(id) }
        }
    }
    if (!s.connected) {
        PairingView(s, vm)
        return
    }
    if (s.sourceRun != null) ResearchSourcesDialog(s, vm)
    val drawer=rememberDrawerState(DrawerValue.Closed)
    val drawerScope=rememberCoroutineScope()
    ModalNavigationDrawer(drawerState=drawer,drawerContent={
        ModalDrawerSheet(Modifier.width(320.dp)) {
            Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceBetween) {
                TextButton(onClick={vm.newChat();drawerScope.launch{drawer.close()}}){Text("＋ New chat")}
                TextButton(onClick={drawerScope.launch{drawer.close()}}){Text("Close")}
            }
            Column(Modifier.weight(1f)){ChatListView(s,vm){drawerScope.launch{drawer.close()}}}
            TextButton(onClick={vm.navigate("settings");drawerScope.launch{drawer.close()}}){Text("Settings")}
        }
    }) {
    Scaffold(
        topBar = {
            // Keep the mode/model controls while giving the editor more space above the IME.
            if (!(s.page in listOf("chat", "work") && WindowInsets.isImeVisible))
            TopAppBar(
                title = {
                    Text(
                        when (s.page) {
                            "hidden" -> "Hidden Chats"
                            "diagnostics" -> "Diagnostics"
                            "settings" -> "Settings"
                            "work" -> "Work"
                            "memory" -> "Memory"
                            "recall" -> "History and retrieval"
                            "models" -> "Models"
                            "devices" -> "Device access"
                            "search" -> "Web search"
                            else -> s.chats.find{it.id==s.selected}?.title ?: "New chat"
                        }
                    )
                },
                navigationIcon = {
                    Row {
                        IconButton(onClick={drawerScope.launch{drawer.open()}},modifier=Modifier.semantics{contentDescription="Open sidebar"}){Text("☰")}
                        IconButton(onClick=vm::newChat,modifier=Modifier.semantics{contentDescription="New chat"}){Text("＋")}
                    }
                },
                actions = {
                    s.chats.find{it.id==s.selected}?.let{ChatActions(it,vm)}
                },
            )
        }
    ) { padding ->
        Column(Modifier.padding(padding).consumeWindowInsets(padding).imePadding().fillMaxSize()) {
            if(s.page in listOf("chat", "chats", "work")) {
                SingleChoiceSegmentedButtonRow(Modifier.align(Alignment.CenterHorizontally).padding(horizontal = 20.dp, vertical = 6.dp)) {
                    listOf("chat" to "Chat", "work" to "Work").forEachIndexed { index, (mode, label) ->
                        SegmentedButton(selected = if(mode == "chat") s.page != "work" else s.page == "work",
                            onClick = {vm.navigate(mode)}, shape = SegmentedButtonDefaults.itemShape(index, 2)) { Text(label) }
                    }
                }
                if(s.page != "chats") GenerationBar(s, vm)
            }
            s.error?.let {
                Row(Modifier.fillMaxWidth().padding(12.dp)) {
                    Text(it, Modifier.weight(1f), color = MaterialTheme.colorScheme.error)
                    TextButton(onClick = vm::errorClear) { Text("Dismiss") }
                }
            }
            Column(Modifier.weight(1f)) { when (s.page) {
                "chat" -> ChatView(s, vm)
                "chats",
                "hidden" -> ChatListView(s, vm)
                "devices" -> DeviceView(s, vm)
                "search" -> SearchSettingsView(s, vm)
                "models" -> ModelsView(models, vm.modelManagement)
                "settings" -> SettingsView(s, vm)
                "recall" -> key(s.origin) { RecallView(vm) }
                "work" -> WorkView(s, vm, export = { id -> workExportTask = id; workExportOrigin = s.origin; workExport.launch("dsGPT-project.zip") }, saveArtifact = { task, a ->
                    artifactTask = task; artifactOrigin = s.origin
                    artifactMetadata = org.json.JSONObject().put("id", a.id).put("execution", a.execution).put("path", a.path).put("bytes", a.bytes).put("sha", a.sha).toString()
                    val ext = if(a.path.endsWith(".apk", true)) "apk" else if(a.path.endsWith(".exe", true)) "exe" else "bin"
                    artifactExport.launch("dsGPT-artifact.$ext")
                }, pickSource = { workSourceOrigin = s.origin; workSourcePicker.launch(arrayOf("*/*")) })
                "memory" -> MemoryView(s, vm) { scope -> memoryExportScope = scope; memoryExportOrigin = s.origin; memoryExport.launch("dsGPT-memory.json") }
                "diagnostics" -> DiagnosticsView(s, vm) { export.launch("dsGPT-Diagnostics.zip") }
            } }
        }
    }
    }
}

@Composable
fun ResearchSourcesDialog(s: State, vm: ChatModel) {
    val context = LocalContext.current
    var openError by remember(s.sourceRun) { mutableStateOf<String?>(null) }
    AlertDialog(
        onDismissRequest = vm::closeSources,
        title = { Text("Research sources") },
        text = {
            Column(Modifier.heightIn(max = 480.dp).verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text("These pages were retrieved for this reply. Check the original page for important claims.")
                if (s.sourcesLoading) Text("Loading sources…")
                if (!s.sourcesLoading && !s.sourcesComplete && s.sourcesError == null) Text("Retrieving sources…")
                if (s.sourcesWarning) Text("Some search engines or pages were unavailable.")
                (s.sourcesError ?: openError)?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                var sourceNumber = 0
                s.sources.forEach { source ->
                    HorizontalDivider()
                    if (source.status == "retrieved") sourceNumber++
                    Text((if (source.status == "retrieved") "S$sourceNumber · " else "") + source.title,
                        style = MaterialTheme.typography.titleSmall)
                    SelectionContainer { Text(source.url, style = MaterialTheme.typography.bodySmall) }
                    Text(when (source.status) {
                        "retrieved" -> "Retrieved ${source.retrieved}"
                        "pending" -> "Retrieval pending"
                        else -> "This page could not be read"
                    }, style = MaterialTheme.typography.bodySmall)
                    if (source.status == "retrieved") {
                        TextButton(onClick = {
                            try {
                                val url = publicSourceUrl(source.url)
                                context.startActivity(android.content.Intent(android.content.Intent.ACTION_VIEW,
                                    android.net.Uri.parse(url)).addCategory(android.content.Intent.CATEGORY_BROWSABLE))
                            } catch (_: Exception) { openError = "This source could not be opened in your browser." }
                        }) { Text("Open source") }
                        source.published?.let { Text("Publication date from page metadata (unverified): $it",
                            style = MaterialTheme.typography.bodySmall) }
                        SelectionContainer { Text("Content SHA-256: ${source.sha256}", style = MaterialTheme.typography.bodySmall) }
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = vm::closeSources) { Text("Close") } },
        dismissButton = { TextButton(onClick = { s.sourceRun?.let(vm::showSources) }, enabled = !s.sourcesLoading) { Text("Refresh") } },
    )
}

@Composable
fun PairingView(s: State, vm: ChatModel) {
    val intent = (LocalContext.current as? android.app.Activity)?.intent
    val suggested = remember {
        setupPairing(intent?.getStringExtra("dsgpt_origin"), intent?.getStringExtra("dsgpt_pairing"))
            .also {
                intent?.removeExtra("dsgpt_pairing")
                intent?.removeExtra("dsgpt_origin")
            }
    }
    var manual by rememberSaveable { mutableStateOf(suggested != null) }
    var origin by rememberSaveable { mutableStateOf(suggested?.first ?: "") }
    var code by remember { mutableStateOf(suggested?.second ?: "") }
    Column(
        Modifier.fillMaxSize()
            .safeDrawingPadding()
            .padding(28.dp)
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.Center,
    ) {
        Text("dsGPT Mobile", style = MaterialTheme.typography.headlineLarge)
        Spacer(Modifier.height(16.dp))
        Text(
            "On your desktop, open dsGPT and choose Connect Pixel automatically. Your phone will open chat when connected."
        )
        Spacer(Modifier.height(12.dp))
        Text("Keep Tailscale connected on both devices. Your existing Wireless debugging connection handles setup over home Wi-Fi.")
        TextButton(onClick = { manual = !manual }) { Text(if (manual) "Hide manual connection" else "Manual connection") }
        if (manual) {
        OutlinedTextField(
            origin,
            { origin = it },
            label = { Text("HTTPS Tailscale address") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(12.dp))
        OutlinedTextField(
            code,
            { code = it },
            label = { Text("Pairing code") },
            visualTransformation = PasswordVisualTransformation(),
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(20.dp))
        Button(
            onClick = { vm.pair(origin, code) },
            enabled = !s.busy && origin.isNotBlank() && code.isNotBlank(),
        ) {
            Text(if (s.busy) "Pairing…" else "Pair this phone")
        }
        }
        s.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
    }
}

@Composable
fun ColumnScope.ChatListView(s: State, vm: ChatModel, onSelected:()->Unit = {}) {
    if (s.page == "chats") {
        Button(onClick = vm::newChat, modifier = Modifier.padding(horizontal = 16.dp)) {
            Text("＋ New chat")
        }
    }
    OutlinedTextField(
        s.query,
        vm::search,
        label = { Text("Search chats") },
        modifier = Modifier.fillMaxWidth().padding(16.dp),
    )
    LazyColumn(Modifier.weight(1f), contentPadding = PaddingValues(horizontal = 16.dp)) {
        items(s.chats, key = { it.id }) { chat ->
            Column {
                if (s.page == "hidden") {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text((if (chat.pinned) "◆ " else "") + chat.title, Modifier.weight(1f))
                        TextButton(onClick = { vm.patch(chat, hidden = false) }) { Text("Unhide") }
                    }
                } else {
                    Row(verticalAlignment=Alignment.CenterVertically) {
                        TextButton(onClick={vm.select(chat);onSelected()},modifier=Modifier.weight(1f)) {
                            Text((if(chat.pinned) "◆ " else "")+chat.title,Modifier.fillMaxWidth())
                        }
                        ChatActions(chat,vm)
                    }
                }
                HorizontalDivider()
            }
        }
    }
}

@Composable
fun SettingsView(s: State, vm: ChatModel) {
    Column(Modifier.padding(24.dp).verticalScroll(rememberScrollState())) {
        Text("Models", style = MaterialTheme.typography.titleLarge)
        Text("Ollama runs your AI on the PC. Standard (-NA) models keep their original training; -A identifies an altered (abliterated) model. Setup automatically adds standard Qwen 3.5 choices and preserves your existing model. The top bar shows thinking controls actually supported by the selected model.")
        TextButton(onClick = { vm.navigate("models") }) { Text("Open Models →") }
        Spacer(Modifier.height(24.dp))
        Text("Web search", style = MaterialTheme.typography.titleLarge)
        Text("Web Auto lets the local model search when public evidence helps, read pages and cite sources. The PC prepares search automatically. Queries use this prompt only; previous chats, memories and attached files are excluded. Choose Off for private prompts. With files attached, automatic search is off.")
        TextButton(onClick = { vm.navigate("search") }) { Text("Search service status →") }
        Spacer(Modifier.height(24.dp))
        Text("Memory", style = MaterialTheme.typography.titleLarge)
        Text("Save facts or preferences for future replies. Memories stay on the PC; you can inspect, edit, export or delete them. Old messages can still contain information copied from a deleted memory.")
        TextButton(onClick = { vm.navigate("memory") }) { Text("Open Memory →") }
        TextButton(onClick = { vm.navigate("recall") }) { Text("History and retrieval →") }
        Spacer(Modifier.height(24.dp))
        Text("Your setup and limits", style = MaterialTheme.typography.titleLarge)
        Text("On a 12 GB GPU / 32 GB RAM PC, standard Qwen 3.5 9B is the responsive option. 27B uses system RAM too and can be much slower. Chat and Work share one GPU. These are local models, not GPT-6; quality, context and file limits differ from ChatGPT.")
        Text("Keep the PC awake, Ollama running and Tailscale connected. Docker supplies isolated builds, document tools and web search; you do not need to operate its interface. Wireless debugging is only for automatic APK updates and connection repair. Turning it off leaves normal Chat, Work and dictation available over Tailscale, removes the debugging access path and avoids background activity. Battery impact varies.")
        Text("Dictation shows partial words as you speak and may revise them. It uses the phone’s on-device speech service; desktop dictation runs locally on your PC in English. Allow microphone access once. No audio recordings are saved. Stop and review before sending.")
        Spacer(Modifier.height(24.dp))
        Text("Chats", style = MaterialTheme.typography.titleLarge)
        TextButton(onClick = { vm.navigate("hidden") }) { Text("Hidden Chats →") }
        Spacer(Modifier.height(24.dp))
        Text("Diagnostics", style = MaterialTheme.typography.titleLarge)
        TextButton(onClick = vm::diagnostics) { Text("Open Diagnostics →") }
        Spacer(Modifier.height(24.dp))
        Text("Device access", style = MaterialTheme.typography.titleLarge)
        TextButton(onClick = { vm.navigate("devices") }) { Text("This phone’s permissions →") }
        Spacer(Modifier.height(24.dp))
        Text("Connection", style = MaterialTheme.typography.titleLarge)
        Text(s.origin)
        TextButton(onClick = vm::disconnect) { Text("Disconnect this phone") }
        Spacer(Modifier.height(24.dp))
        Text("Work", style = MaterialTheme.typography.titleLarge)
        TextButton(onClick = { vm.navigate("work") }) { Text("Open Work →") }
    }
}

@Composable
fun DiagnosticsView(s: State, vm: ChatModel, export: () -> Unit) {
    var consent by remember(s.phonePreview) { mutableStateOf(false) }
    Column(Modifier.padding(24.dp).verticalScroll(rememberScrollState())) {
        Text("Sanitized diagnostics", style = MaterialTheme.typography.titleLarge)
        Text(
            "Preview app health, device model, timing, memory, thermal and connection measurements before sharing. Local failure history stays on this phone until you share a reviewed snapshot. Chats and credentials are excluded."
        )
        TextButton(onClick = vm::previewPhoneSnapshot) { Text("Preview phone snapshot") }
        if (s.pendingCollections.isNotEmpty()) {
            Text("Your PC requested a fresh snapshot. Sharing requires your consent here.")
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Checkbox(consent, { consent = it })
            Text("I agree to share this snapshot with my PC.", Modifier.weight(1f))
        }
        Button(
            onClick = {
                vm.shareSnapshot()
                consent = false
            },
            enabled = consent && s.phonePreview.isNotBlank(),
        ) {
            Text("Share phone snapshot")
        }
        TextButton(onClick = vm::manualDesktopSnapshot) { Text("Save PC snapshot now") }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Checkbox(s.includeBuildLogs, vm::includeBuildLogs)
            Text("Include build/test output. Project text, paths or unrecognized secrets may remain; review before sharing.", Modifier.weight(1f))
        }
        TextButton(onClick = vm::preview) { Text("Preview diagnostic export") }
        if (s.exportId != null || s.phonePreview.isNotBlank()) {
            TextButton(onClick = export) { Text("Save reviewed export…") }
        }
        DiagnosticCategories(s.diagnostics)
        if (s.phonePreview.isNotBlank()) SelectionContainer { Text(s.phonePreview) }
    }
}

@Composable
fun ChatView(s: State, vm: ChatModel) {
    var pickerSession by rememberSaveable { mutableStateOf("") }
    val attachmentPicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if(uri != null && pickerSession.isNotBlank()) vm.addAttachment(uri, pickerSession)
        pickerSession = ""
    }
    val context = LocalContext.current
    val prefs = remember { context.getSharedPreferences("reading", Context.MODE_PRIVATE) }
    val id = s.selected ?: "new"
    key(id) {
        val list =
            rememberLazyListState(prefs.getInt("$id:index", 0), prefs.getInt("$id:offset", 0))
        var following by
            rememberSaveable(id) { mutableStateOf(prefs.getBoolean("$id:follow", true)) }
        var initialized by remember(id) { mutableStateOf(false) }
        var programmatic by remember(id) { mutableStateOf(false) }
        val scope = rememberCoroutineScope()
        val lifecycle = LocalLifecycleOwner.current
        fun save() {
            prefs
                .edit()
                .putInt("$id:index", list.firstVisibleItemIndex)
                .putInt("$id:offset", list.firstVisibleItemScrollOffset)
                .putBoolean("$id:follow", following)
                .apply()
        }
        DisposableEffect(id, lifecycle) {
            val observer = LifecycleEventObserver { _, event ->
                if (event == Lifecycle.Event.ON_STOP) save()
            }
            lifecycle.lifecycle.addObserver(observer)
            onDispose {
                save()
                lifecycle.lifecycle.removeObserver(observer)
            }
        }
        LaunchedEffect(list) {
            snapshotFlow { list.isScrollInProgress to list.canScrollForward }
                .collect { (scrolling, forward) ->
                    if (initialized && scrolling && !programmatic) following = !forward
                }
        }
        suspend fun bottom() {
            if (s.messages.isEmpty()) return
            programmatic = true
            try {
                list.scrollToItem(s.messages.lastIndex)
                val last = list.layoutInfo.visibleItemsInfo.lastOrNull()
                if (last != null)
                    list.scrollBy(
                        (last.offset + last.size - list.layoutInfo.viewportEndOffset)
                            .coerceAtLeast(0)
                            .toFloat()
                    )
            } finally {
                programmatic = false
            }
        }
        LaunchedEffect(s.messages) {
            if (s.messages.isNotEmpty()) {
                if (following) bottom()
                initialized = true
            }
        }
        var dictating by remember { mutableStateOf(false) }
        var filesOpen by remember { mutableStateOf(false) }
        var researchOptionsOpen by remember { mutableStateOf(false) }
        Column(Modifier.fillMaxSize()) {
            if (s.messages.isEmpty())
                Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                    if (s.draft.isBlank())
                    Text(
                        "What would you like to explore?",
                        style = MaterialTheme.typography.titleLarge,
                    )
                }
            else
                LazyColumn(
                    state = list,
                    modifier = Modifier.weight(1f).fillMaxWidth(),
                    contentPadding = PaddingValues(20.dp),
                    verticalArrangement = Arrangement.spacedBy(24.dp),
                ) {
                    items(s.messages, key = { it.id }) { message ->
                        Column {
                            Text(
                                if (message.role == "user") "You" else "dsGPT · ${message.status}",
                                color = MaterialTheme.colorScheme.primary,
                                style = MaterialTheme.typography.labelMedium,
                            )
                            Spacer(Modifier.height(8.dp))
                            SelectionContainer {
                                Text(message.content.ifBlank { "Waiting for the local model…" })
                            }
                            message.errorCode?.let { Text(if(it == "context_exceeded") "This message and its files exceed the model’s context. Choose a larger context/model or send less text. Nothing was silently shortened." else if(it == "local_vision_model_required") "Choose a locally installed Ollama model with vision support to interpret this image. No pixels were sent to a text-only model." else "Reply stopped: $it", color = MaterialTheme.colorScheme.error) }
                            message.attachments.forEach { file -> TextButton(onClick = { vm.showAttachment(file) }) { Text("Attached file: ${file.name}" + if(file.removed) " (removed)" else "") } }
                            if (message.research && message.runId != null) {
                                TextButton(onClick = { vm.showSources(message.runId) }) { Text("View sources") }
                            }
                        }
                    }
                }
            if (!following && s.messages.isNotEmpty())
                TextButton(
                    onClick = {
                        following = true
                        scope.launch { bottom() }
                    },
                    modifier = Modifier.align(Alignment.CenterHorizontally),
                ) {
                    Text("↓ Jump to latest")
                }
            if (filesOpen) AlertDialog(
                onDismissRequest = { filesOpen = false },
                title = { Text("Files and sources") },
                text = { Column(Modifier.verticalScroll(rememberScrollState())) {
                TextButton(onClick = { pickerSession = s.attachmentSession; attachmentPicker.launch(arrayOf("*/*")) }, enabled = !s.busy && !s.readingAttachment && !s.researchEnabled && s.attachments.size < 4) { Text(if(s.readingAttachment) "Reading file…" else "Attach file/image…") }
                Text("Text, code, documents or images · 4 files · 64 KiB each · 128 KiB total. Turn off Research to attach. Originals: 512 KiB each, 768 KiB total. Selected documents go to the PC for an unsaved preview. PDF/image OCR and XLSX/PPTX require isolated document tools. Images require a local Ollama vision model.", style = MaterialTheme.typography.bodySmall)
                s.attachments.forEachIndexed { index, file -> Column {
                    file.documentNotice?.let { Text(it, style = MaterialTheme.typography.bodySmall); Text(file.text.take(2000)); if(file.text.length > 2000) Text("Preview shows the first 2,000 characters; full extracted text is attached.") }
                    Row {
                    Text("${file.name} · ${file.text.toByteArray(Charsets.UTF_8).size} bytes", Modifier.weight(1f))
                    TextButton(onClick = { vm.removeSelectedAttachment(index) }, enabled = !s.busy && !s.readingAttachment) { Text("Remove") }
                } } }
                if(s.attachments.isNotEmpty()) Text("Saved on the PC when your message is accepted. Unsent selections are lost after app process death. Model context limits still apply; file text is not silently shortened.", style = MaterialTheme.typography.bodySmall)
                Row(verticalAlignment = Alignment.CenterVertically) {
                Checkbox(s.researchEnabled, vm::research, enabled = s.researchAvailable && !s.busy && !s.readingAttachment && s.attachments.isEmpty())
                Text("Sources", Modifier.weight(1f))
                if (s.researchEnabled) TextButton(onClick = { filesOpen = false; researchOptionsOpen = true }) { Text("Options") }
                }
                Text("${s.status} · Replies continue on your PC.", style = MaterialTheme.typography.labelSmall)
                } },
                confirmButton = { TextButton(onClick = { filesOpen = false }) { Text("Done") } },
            )
            if (researchOptionsOpen) AlertDialog(
                onDismissRequest = { researchOptionsOpen = false },
                title = { Text("Research settings") },
                text = { Column(Modifier.verticalScroll(rememberScrollState())) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(s.searchWeb, vm::searchWeb, enabled = s.searchConfigured && !s.busy)
                        Text("Search the web")
                    }
                    if (!s.searchConfigured) Text("Web search is not configured on your PC. You can still read source URLs.")
                    OutlinedTextField(s.sourceUrls, vm::sourceUrls, label = { Text("Source URLs") },
                        placeholder = { Text("Public HTTPS URLs, one per line (up to six)") }, maxLines = 5,
                        enabled = !s.busy, modifier = Modifier.fillMaxWidth().padding(vertical = 12.dp))
                    Text(if (s.searchWeb) "Queries based on this message go to public search services. Earlier messages, attached files and saved memories are not sent."
                        else "Your PC will read the supplied public pages. Inference stays on your PC.")
                } },
                confirmButton = { TextButton(onClick = { researchOptionsOpen = false }) { Text("Done") } },
            )
            PromptComposer(
                value = s.draft, onValue = vm::draft, hint = "Message dsGPT", enabled = !s.busy,
                canSend = !s.busy && !dictating && !s.readingAttachment && s.draft.isNotBlank() && s.model.isNotBlank(),
                onSend = { following = true; vm.send() },
                stop = if (s.run != null) vm::stop else null,
            ) {
                TextButton(onClick = { filesOpen = true }) {
                    Text(if (s.attachments.isEmpty()) "＋ Files" else "＋ Files (${s.attachments.size})")
                }
                WebMode(if(s.attachments.isNotEmpty()) "off" else s.webMode, !s.busy && s.attachments.isEmpty(), vm::webMode)
                LiveDictation(s.draft, !s.busy, vm::draft, compact = true) { dictating = it }
            }
        }
    }
}


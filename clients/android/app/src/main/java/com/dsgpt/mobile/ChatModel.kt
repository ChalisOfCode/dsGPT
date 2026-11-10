package com.dsgpt.mobile

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import java.net.URLEncoder
import java.util.UUID
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import org.json.JSONArray
import org.json.JSONObject

data class Chat(
    val id: String,
    val title: String,
    val pinned: Boolean,
    val revision: Int,
    val model: String,
)

data class Message(val id: String, val role: String, val content: String, val status: String,
                   val runId: String? = null, val research: Boolean = false, val attachments: List<AttachmentRecord> = emptyList(), val errorCode: String? = null)

data class Model(val id: String, val label: String)

data class State(
    val connected: Boolean = false,
    val connectionEpoch: Long = 0,
    val origin: String = "",
    val chats: List<Chat> = emptyList(),
    val messages: List<Message> = emptyList(),
    val models: List<Model> = emptyList(),
    val model: String = "",
    val selected: String? = null,
    val page: String = "chat",
    val effort: String = "auto",
    val webMode: String = "auto",
    val thinkingChoices: List<Pair<String, String>> = listOf("auto" to "Model default"),
    val query: String = "",
    val draft: String = "",
    val run: String? = null,
    val busy: Boolean = false,
    val error: String? = null,
    val status: String = "Ready",
    val diagnostics: String = "",
    val phonePreview: String = "",
    val includeBuildLogs: Boolean = false,
    val pendingCollections: List<String> = emptyList(),
    val exportId: String? = null,
    val exportHash: String? = null,
    val researchAvailable: Boolean = false,
    val searchConfigured: Boolean = false,
    val researchEnabled: Boolean = false,
    val searchWeb: Boolean = false,
    val sourceUrls: String = "",
    val sourceRun: String? = null,
    val sources: List<ResearchSource> = emptyList(),
    val sourcesLoading: Boolean = false,
    val sourcesComplete: Boolean = false,
    val sourcesWarning: Boolean = false,
    val sourcesError: String? = null,
    val work: WorkState = WorkState(),
    val memory: MemoryUi = MemoryUi(),
    val device: DeviceUi = DeviceUi(),
    val searchSetup: SearchUi = SearchUi(),
    val attachments: List<DraftAttachment> = emptyList(),
    val attachmentSession: String = UUID.randomUUID().toString(),
    val readingAttachment: Boolean = false,
    val attachmentView: AttachmentPage? = null,
)

fun messages(json: JSONArray) =
    List(json.length()) { i ->
        json.getJSONObject(i).let {
            Message(
                it.getString("id"),
                it.getString("role"),
                it.getString("content"),
                it.getString("status"),
                if (it.isNull("run_id")) null else it.optString("run_id").ifBlank { null },
                it.optInt("research", 0) == 1,
                attachmentRecords(it.optJSONArray("attachments")),
                if(it.isNull("run_error_code")) null else it.optString("run_error_code").ifBlank { null },
            )
        }
    }

class ChatModel(app: Application) : AndroidViewModel(app) {
    private val vault = Vault(app)
    private var api: Api? = null
    private val mutable = MutableStateFlow(State())
    val state = mutable.asStateFlow()
    private val preferences =
        app.getSharedPreferences("navigation", android.content.Context.MODE_PRIVATE)
    private var requestId: String? = null
    private var workRequestId: String? = null
    private var workSourceEpoch = 0
    private var memoryRequestId: String? = null
    private var memoryEpoch: Int = 0
    private var memorySearch: Job? = null

    val modelManagement = ModelManager(viewModelScope, { api }) { models ->
        mutable.update { it.copy(models = models, model = it.model.takeIf { id -> models.any { m -> m.id == id } } ?: models.firstOrNull()?.id ?: "") }
    }

    private var savedConnectionRevision: String? = null

    init {
        action {
            api = vault.load()
            savedConnectionRevision = vault.revision()
            if (api != null) {
                mutable.update { it.copy(connected = true, origin = api!!.origin, connectionEpoch = it.connectionEpoch + 1) }
                loadModels()
                loadChats()
                val previous = preferences.getString("${api!!.origin}:selected", null)
                state.value.chats.find { it.id == previous }?.let { select(it) }
            }
        }
    }

    private fun action(block: suspend () -> Unit) =
        viewModelScope.launch {
            try {
                block()
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                MobileTelemetry.record(DiagnosticEvent.HANDLED)
                mutable.update { it.copy(error = e.message ?: "Operation failed", busy = false) }
            }
        }

    fun restoreUpdatedConnection() {
        val revision=vault.revision()
        if(revision==null || revision==savedConnectionRevision)return
        action {
            val restored=vault.load() ?: return@action
            api=restored;savedConnectionRevision=revision
            modelManagement.reset()
            mutable.update {it.copy(connected=true,origin=restored.origin,error=null,connectionEpoch=it.connectionEpoch+1)}
            loadModels();loadChats()
        }
    }

    suspend fun observeConnection() {
        while(currentCoroutineContext().isActive) {
            val connection=api
            if(connection!=null) {
                try {
                    connection.request("/v1/device/heartbeat", "POST", JSONObject().put("app_version", BuildConfig.VERSION_NAME))
                    if(api===connection && state.value.models.isEmpty()) {loadModels();loadChats()}
                } catch(e: CancellationException) {throw e} catch(_:Exception) { /* Retain credentials and retry after network changes. */ }
            }
            delay(30_000)
        }
    }

    fun errorClear() {
        mutable.update { it.copy(error = null) }
    }

    fun pair(origin: String, code: String) {
        mutable.update { it.copy(busy = true) }
        action {
            val connected = Api.pair(origin, code)
            connected.persist(vault)
            savedConnectionRevision = vault.revision()
            api = connected
            modelManagement.reset()
            mutable.update { it.copy(connected = true, origin = connected.origin, busy = false, connectionEpoch = it.connectionEpoch + 1) }
            loadModels()
            loadChats()
        }
    }

    private suspend fun loadModels() {
        val json = JSONArray(api!!.request("/v1/models"))
        val models =
            List(json.length()) { i ->
                json.getJSONObject(i).let { Model(it.getString("id"), it.getString("label")) }
            }
        mutable.update {
            it.copy(models = models, model = it.model.ifBlank { models.firstOrNull()?.id ?: "" })
        }
        refreshResearchCapabilities(initial = !state.value.researchAvailable)
    }

    private suspend fun refreshResearchCapabilities(initial: Boolean = false) {
        val connection = api ?: return
        try {
            val capability = JSONObject(connection.request("/v1/research/capabilities"))
            if(api !== connection) return
            val configured = capability.optBoolean("search_configured")
            mutable.update { it.copy(researchAvailable = capability.optBoolean("public_page_reading"),
                searchConfigured = configured, searchWeb = configured && (initial || it.searchWeb)) }
        } catch(e: CancellationException) { throw e }
        catch(_: Exception) { /* Retain last capability; accepted requests still belong to the PC. */ }
    }

    private var searchStatusEpoch = 0
    suspend fun refreshSearchSettings() {
        val epoch = ++searchStatusEpoch
        val connection = api ?: return
        mutable.update { it.copy(searchSetup = it.searchSetup.copy(loading = true)) }
        try {
            val j = JSONObject(connection.request("/v1/research/settings"))
            val last = j.optJSONObject("last_check")
            val status = SearchStatus(if(j.isNull("origin")) null else j.getString("origin"),
                j.optBoolean("configuration_owned"), j.optBoolean("check_in_progress"), last?.let {
                    SearchTest(it.getString("status"), it.getString("checked_at"), it.getInt("result_count"),
                        it.getInt("engine_failures"), if(it.isNull("error_code")) null else it.getString("error_code")) })
            if(api === connection && epoch == searchStatusEpoch) mutable.update { it.copy(searchSetup = SearchUi(status = status),
                searchConfigured = j.optBoolean("configured"), searchWeb = it.searchWeb && j.optBoolean("configured")) }
        } catch(e: CancellationException) { throw e }
        catch(e: Exception) { if(api === connection && epoch == searchStatusEpoch) mutable.update { it.copy(searchSetup = it.searchSetup.copy(
            error = (e.message ?: "Search status unavailable") + ". Requires PC backend 0.3.0.dev10 or newer and Chat access.")) } }
        finally { if(api === connection && epoch == searchStatusEpoch) mutable.update { it.copy(searchSetup = it.searchSetup.copy(loading = false)) } }
    }
    fun refreshSearchNow() { action { refreshSearchSettings() } }
    suspend fun observeSearchReadiness() {
        while(currentCoroutineContext().isActive && state.value.connected && state.value.page in listOf("chat", "chats", "search", "work")) {
            if(state.value.page == "search") refreshSearchSettings() else refreshResearchCapabilities()
            loadModels()
            delay(10000)
        }
    }

    suspend fun loadChats() {
        val hidden = state.value.page == "hidden"
        val q = state.value.query
        val chats = mutableListOf<Chat>()
        var offset = 0
        do {
            val rows =
                JSONArray(
                    api!!.request(
                        "/v1/conversations?hidden=$hidden&q=${URLEncoder.encode(q,"UTF-8")}&limit=200&offset=$offset"
                    )
                )
            for (i in 0 until rows.length()) {
                val c = rows.getJSONObject(i)
                chats +=
                    Chat(
                        c.getString("id"),
                        c.getString("title"),
                        c.getInt("pinned") == 1,
                        c.getInt("revision"),
                        c.optString("model_id", ""),
                    )
            }
            offset += rows.length()
        } while (rows.length() == 200)
        if (hidden == (state.value.page == "hidden") && q == state.value.query)
            mutable.update { it.copy(chats = chats) }
    }

    fun search(value: String) {
        mutable.update { it.copy(query = value) }
        action { loadChats() }
    }

    fun navigate(page: String) {
        mutable.update { it.copy(page = page, query = "") }
        if (page == "work" && state.value.work.selected == null) {
            preferences.getString("${api?.origin}:work", null)?.let { selectWork(it) }
        }
        if (page == "chats" || page == "hidden") action { loadChats() }
    }

    fun select(chat: Chat) {
        attachmentReadEpoch++
        preferences.edit().putString("${api!!.origin}:selected", chat.id).apply()
        mutable.update {
            it.copy(
                selected = chat.id,
                attachments = emptyList(), attachmentSession = UUID.randomUUID().toString(), readingAttachment = false, attachmentView = null,
                page = "chat",
                messages = emptyList(),
                model =
                    chat.model.takeIf { m -> state.value.models.any { it.id == m } } ?: it.model,
                draft = "",
                run = null,
                researchEnabled = false, sourceUrls = "", sourceRun = null, sources = emptyList(),
            )
        }
        requestId = null
    }

    fun newChat() {
        attachmentReadEpoch++
        preferences.edit().remove("${api!!.origin}:selected").apply()
        mutable.update {
            it.copy(selected = null, page = "chat", messages = emptyList(), draft = "", run = null,
                attachments = emptyList(), attachmentSession = UUID.randomUUID().toString(), readingAttachment = false, attachmentView = null,
                researchEnabled = false, sourceUrls = "", sourceRun = null, sources = emptyList())
        }
        requestId = null
    }

    fun draft(value: String) {
        requestId = null
        mutable.update { it.copy(draft = value) }
    }

    fun model(value: String) {
        requestId = null
        workRequestId = null
        mutable.update { it.copy(model = value) }
    }

    fun effort(value: String) { requestId = null; workRequestId = null; mutable.update { it.copy(effort = value) } }
    fun webMode(value: String) { requestId = null; workRequestId = null; mutable.update { it.copy(webMode = value) } }
    suspend fun loadThinking() {
        val connection = api ?: return
        val model = state.value.model
        if(model.isBlank()) return
        try {
            val j = JSONObject(connection.request("/v1/models/${java.net.URLEncoder.encode(model, "UTF-8")}/thinking"))
            val choices = j.getJSONArray("choices")
            val values = List(choices.length()) { index -> choices.getJSONObject(index).let { it.getString("id") to it.getString("label") } }
            if(api === connection && state.value.model == model) mutable.update { it.copy(thinkingChoices = values, effort = it.effort.takeIf { selected -> values.any { c -> c.first == selected } } ?: "auto") }
        } catch(e: CancellationException) { throw e }
        catch(_: Exception) { if(api === connection && state.value.model == model) mutable.update { it.copy(thinkingChoices = listOf("auto" to "Model default"), effort = "auto") } }
    }

    fun research(value: Boolean) {
        requestId = null
        mutable.update { it.copy(researchEnabled = value && it.researchAvailable) }
    }
    fun searchWeb(value: Boolean) {
        requestId = null
        mutable.update { it.copy(searchWeb = value && it.searchConfigured) }
    }
    fun sourceUrls(value: String) {
        requestId = null
        mutable.update { it.copy(sourceUrls = value) }
    }

    fun closeSources() { mutable.update { it.copy(sourceRun = null) } }

    fun showSources(runId: String) {
        val chatId = state.value.selected
        mutable.update { it.copy(sourceRun = runId, sources = emptyList(), sourcesLoading = true,
            sourcesError = null, sourcesWarning = false, sourcesComplete = false) }
        action {
            try {
                val result = JSONObject(api!!.request("/v1/runs/$runId/sources"))
                val rows = result.getJSONArray("sources")
                val sources = List(rows.length()) { i ->
                    val row = rows.getJSONObject(i)
                    ResearchSource(row.getString("id"), row.optString("final_url").ifBlank { row.getString("url") },
                        row.optString("title", "Source"), row.getString("status"), row.optString("retrieved_at"),
                        if (row.isNull("published_at")) null else row.optString("published_at"),
                        row.optString("content_sha256"))
                }
                mutable.update { if (it.sourceRun == runId && it.selected == chatId) it.copy(sources = sources,
                    sourcesLoading = false, sourcesComplete = result.optBoolean("retrieval_complete"),
                    sourcesWarning = (result.optJSONArray("warnings")?.length() ?: 0) > 0) else it }
            } catch (e: CancellationException) { throw e }
            catch (_: Exception) { mutable.update { if (it.sourceRun == runId && it.selected == chatId)
                it.copy(sourcesLoading = false, sourcesError = "Sources are unavailable. Try again when connected.") else it } }
        }
    }

    fun patch(chat: Chat, hidden: Boolean? = null, pinned: Boolean? = null, title: String? = null) {
        action {
            val body = JSONObject().put("revision", chat.revision)
            if (title != null) body.put("title", title)
            if (hidden != null) body.put("hidden", hidden)
            if (pinned != null) body.put("pinned", pinned)
            api!!.request("/v1/conversations/${chat.id}", "PATCH", body)
            loadChats()
        }
    }

    fun deleteChat(chat:Chat) {action {
        val connection=api ?: return@action
        connection.request("/v1/conversations/${chat.id}","DELETE")
        if(api===connection){if(state.value.selected==chat.id)newChat();loadChats()}
    }}
    suspend fun chatFiles(id:String,offset:Int=0):List<AttachmentRecord> {
        val connection=api ?: error("Connect first")
        return attachmentRecords(JSONArray(connection.request("/v1/conversations/${workTaskId(id)}/files?offset=$offset")))
    }

    fun send() {
        val s = state.value
        if (s.busy || s.readingAttachment || s.draft.isBlank() || s.model.isBlank() || s.run != null) return
        mutable.update { it.copy(busy = true) }
        action {
            if(s.attachments.isNotEmpty()) {
                validateAttachments(s.attachments)
                require(!s.researchEnabled) { "Turn off Research to send private text files." }
                val capability = JSONObject(api!!.request("/v1/capabilities"))
                require(capability.optJSONObject("attachments")?.optBoolean("chat_text_files") == true) { "Text attachments require PC backend 0.3.0.dev11 or newer. Your selected files are retained." }
            }
            val research = if (s.researchEnabled) JSONObject().put("search", s.searchWeb)
                .put("urls", JSONArray(researchUrls(s.searchWeb, s.sourceUrls))) else null
            var id = s.selected
            if (id == null) {
                id =
                    JSONObject(
                            api!!.request(
                                "/v1/conversations",
                                "POST",
                                JSONObject().put("title", s.draft.take(80)),
                            )
                        )
                        .getString("id")
                mutable.update { it.copy(selected = id) }
            }
            val request = requestId ?: UUID.randomUUID().toString().also { requestId = it }
            val run =
                JSONObject(
                    api!!.request(
                        "/v1/conversations/$id/messages",
                        "POST",
                        JSONObject()
                            .put("request_id", request)
                            .put("content", s.draft)
                            .put("model_id", s.model).put("reasoning_effort", s.effort).put("web_mode", if(s.attachments.isNotEmpty() || s.researchEnabled) "off" else s.webMode)
                            .apply { if (research != null) put("research", research); if(s.attachments.isNotEmpty()) put("attachments", attachmentJson(s.attachments)) },
                    )
                )
            requestId = null
            mutable.update { it.copy(draft = "", attachments = emptyList(), busy = false, run = run.getString("id")) }
        }
    }

    private var attachmentReadEpoch = 0
    fun addAttachment(uri: android.net.Uri, expectedSession: String) {
        val connection = api ?: return
        if(state.value.attachmentSession != expectedSession || state.value.busy || state.value.readingAttachment) return
        mutable.update { it.copy(readingAttachment = true) }
        action {
            try {
                var file = withContext(Dispatchers.IO) { readAttachment(getApplication<Application>().contentResolver, uri, allowDocx = true) }
                if(api !== connection || state.value.attachmentSession != expectedSession) return@action
                if(file.originalBase64 != null) {
                    val preview = JSONObject(connection.request("/v1/documents/preview", "POST", JSONObject().put("name", file.name).put("original_base64", file.originalBase64)))
                    file = file.copy(text = preview.getString("text"), documentNotice = preview.getJSONObject("document").getString("notice"))
                }
                if(api !== connection || state.value.attachmentSession != expectedSession) return@action
                require(!state.value.researchEnabled) { "Turn off Research to attach text files." }
                val files = state.value.attachments + file; validateAttachments(files)
                requestId = null; mutable.update { it.copy(attachments = files) }
            } finally { if(api === connection && state.value.attachmentSession == expectedSession) mutable.update { it.copy(readingAttachment = false) } }
        }
    }
    fun removeSelectedAttachment(index: Int) { if(!state.value.busy && !state.value.readingAttachment) {
        requestId = null; mutable.update { it.copy(attachments = it.attachments.filterIndexed { i, _ -> i != index }) }
    } }
    fun showAttachment(file: AttachmentRecord, conversationId: String? = null) {
        attachmentReadEpoch++
        val chat = conversationId ?: state.value.selected ?: return
        mutable.update { it.copy(attachmentView = AttachmentPage(chat, file)) }
        if(!file.removed) readAttachmentPage(0)
    }
    fun closeAttachment() { attachmentReadEpoch++; mutable.update { it.copy(attachmentView = null) } }
    fun readAttachmentPage(offset: Int) {
        val page = state.value.attachmentView ?: return
        val connection = api ?: return
        val own = ++attachmentReadEpoch
        mutable.update { it.copy(attachmentView = page.copy(loading = true, error = null, text = null)) }
        action {
            try {
                val j = JSONObject(connection.request("/v1/conversations/${page.chatId}/attachments/${page.file.id}?offset=$offset"))
                if(api === connection && attachmentReadEpoch == own) mutable.update { it.copy(attachmentView = page.copy(
                    text = j.getString("text"), offset = j.getInt("offset"), total = j.getInt("total_characters"),
                    next = if(j.isNull("next_offset")) null else j.getInt("next_offset"), loading = false, error = null)) }
            } catch(e: CancellationException) { throw e }
            catch(e: Exception) { if(api === connection && attachmentReadEpoch == own) mutable.update { it.copy(attachmentView = page.copy(loading = false,
                file = page.file.copy(removed = page.file.removed || e.message?.contains("410") == true), error = e.message ?: "Attachment unavailable")) } }
        }
    }
    fun removeStoredAttachment() {
        val page = state.value.attachmentView ?: return; val connection = api ?: return
        if(page.loading) return
        val own = ++attachmentReadEpoch
        mutable.update { it.copy(attachmentView = page.copy(loading = true, error = null)) }
        action {
            try {
                connection.request("/v1/conversations/${page.chatId}/attachments/${page.file.id}", "DELETE")
                if(api === connection && attachmentReadEpoch == own) mutable.update { it.copy(attachmentView = page.copy(file = page.file.copy(removed = true), text = null,
                    notice = "Stored file body removed. Message text, replies and older backups remain.")) }
            } catch(e: CancellationException) { throw e }
            catch(e: Exception) { if(api === connection && attachmentReadEpoch == own) mutable.update { it.copy(attachmentView = page.copy(error = (e.message ?: "Removal failed") + " Refresh before retrying; no action is replayed automatically.")) } }
        }
    }
    fun saveAttachment(chatId: String, id: String, expectedSession: String, uri: android.net.Uri) {
        val connection = api ?: return
        if(state.value.attachmentSession != expectedSession) return
        action {
            val bytes = connection.downloadAttachment(chatId, id)
            if(api !== connection || state.value.attachmentSession != expectedSession) return@action
            withContext(Dispatchers.IO) { getApplication<Application>().contentResolver.openOutputStream(uri)?.use { it.write(bytes) } ?: error("Unable to save attachment") }
        }
    }

    fun stop() {
        val id = state.value.run ?: return
        action { api!!.request("/v1/runs/$id/cancel", "POST") }
    }

    /** Called only inside repeatOnLifecycle(STARTED); network observation stops in background. */
    suspend fun observeChat(id: String) {
        val all = mutableListOf<Message>()
        var lastOrdinal = 0
        while (
            currentCoroutineContext().isActive &&
                state.value.selected == id &&
                state.value.page == "chat"
        ) {
            try {
                var after = (lastOrdinal - 2).coerceAtLeast(0)
                do {
                    val batch =
                        JSONArray(
                            api!!.request("/v1/conversations/$id/messages?after=$after&limit=200")
                        )
                    for (message in messages(batch)) {
                        val index = all.indexOfFirst { it.id == message.id }
                        if (index >= 0) all[index] = message else all += message
                    }
                    if (batch.length() > 0)
                        after = batch.getJSONObject(batch.length() - 1).getInt("ordinal")
                    lastOrdinal = after
                } while (batch.length() == 200)
                val raw = api!!.request("/v1/conversations/$id/latest-run")
                var active: String? = null
                if (raw != "null") {
                    val snapshot = JSONObject(raw)
                    val m = messages(JSONArray().put(snapshot.getJSONObject("message"))).first()
                    val index = all.indexOfFirst { it.id == m.id }
                    // A newly created pair is fetched together on the next tail refresh.
                    if (index >= 0) all[index] = m
                    val run = snapshot.getJSONObject("run")
                    if (run.getString("status") in listOf("queued", "running"))
                        active = run.getString("id")
                }
                if (state.value.selected == id)
                    mutable.update {
                        it.copy(messages = all.toList(), run = active, status = "Connected")
                    }
                delay(if (active == null) 1800 else 300)
            } catch (e: CancellationException) {
                throw e
            } catch (_: Exception) {
                MobileTelemetry.record(DiagnosticEvent.STREAM)
                mutable.update { it.copy(status = "Reconnecting…") }
                delay(1800)
            }
        }
    }

    fun diagnostics() {
        navigate("diagnostics")
        mutable.update { it.copy(exportId = null, exportHash = null, phonePreview = "") }
        action {
            val overview = JSONObject(api!!.request("/v1/diagnostics/overview")).toString(2)
            val pending = JSONArray(api!!.request("/v1/diagnostics/collections"))
            mutable.update {
                it.copy(
                    diagnostics = overview,
                    pendingCollections =
                        List(pending.length()) { i -> pending.getJSONObject(i).getString("id") },
                )
            }
        }
    }

    fun previewPhoneSnapshot() {
        val body = MobileTelemetry.snapshot().toString(2)
        mutable.update { it.copy(phonePreview = body, diagnostics = body, exportId = null, exportHash = null) }
    }

    fun includeBuildLogs(value: Boolean) {
        mutable.update { it.copy(includeBuildLogs = value, exportId = null, exportHash = null) }
    }

    fun manualDesktopSnapshot() { action {
        api!!.request("/v1/diagnostics/snapshots", "POST", JSONObject())
        mutable.update { it.copy(status = "PC snapshot saved") }
        diagnostics()
    } }

    fun shareSnapshot() {
        val reviewed = state.value.phonePreview.takeIf { it.isNotBlank() } ?: return
        action {
            val body = JSONObject(reviewed)
            val collection = state.value.pendingCollections.firstOrNull()
            api!!.request(
                "/v1/diagnostics/mobile" + (collection?.let { "?collection_id=$it" } ?: ""),
                "POST",
                body,
            )
            mutable.update {
                it.copy(
                    status = "Phone snapshot shared with your PC",
                    pendingCollections = it.pendingCollections.drop(1),
                )
            }
        }
    }

    fun preview() {
        action {
            val preview =
                JSONObject(api!!.request("/v1/diagnostics/exports/preview", "POST",
                    JSONObject().put("include_work_logs", state.value.includeBuildLogs)))
            mutable.update {
                it.copy(
                    diagnostics = preview.toString(2),
                    phonePreview = "",
                    exportId = preview.getString("id"),
                    exportHash = preview.getString("sha256"),
                )
            }
        }
    }

    fun saveExport(uri: android.net.Uri) {
        val s = state.value
        if (s.exportId == null && s.phonePreview.isBlank()) return
        action {
            val bytes = if (s.exportId != null && s.exportHash != null) api!!.download(s.exportId, s.exportHash)
                else phoneDiagnosticArchive(s.phonePreview)
            withContext(Dispatchers.IO) {
                getApplication<Application>().contentResolver.openOutputStream(uri)?.use {
                    it.write(bytes)
                } ?: error("Unable to save export")
            }
        }
    }

    private fun updateWork(change: (WorkState) -> WorkState) {
        mutable.update { it.copy(work = change(it.work)) }
    }

    fun editWork(field: String, value: String) {
        if (state.value.work.busy) return
        if (field in listOf("title", "requirements", "model", "references", "target", "publicQuery", "followLinks")) workRequestId = null
        updateWork { when(field) {
            "target" -> if(value in listOf("source", "files", "exe", "apk")) it.copy(target = value) else it
            "title" -> it.copy(title = value.take(300))
            "requirements" -> it.copy(requirements = value.take(1500000))
            "model" -> it.copy(model = value)
            "publicQuery" -> it.copy(publicQuery = value.take(500))
            "followLinks" -> it.copy(followLinks = value == "true")
            "references" -> it.copy(references = value.take(24600))
            "extraReferences" -> it.copy(extraReferences = value.take(24600), editRevision = it.editRevision ?: it.task?.revision)
            "retrySources" -> it.copy(retrySources = value == "true", editRevision = it.editRevision ?: it.task?.revision)
            "note" -> it.copy(note = value.take(1500000), editRevision = it.editRevision ?: it.task?.revision)
            "editWeb" -> it.copy(editWeb = value, editRevision = it.editRevision ?: it.task?.revision)
            "editModel" -> it.copy(editModel = value, editRevision = it.editRevision ?: it.task?.revision)
            else -> it
        } }
    }

    private fun accountReadConnection(task: String, revision: Int, epoch: Long): Api {
        val s = state.value
        check(s.connected && s.page == "work" && s.connectionEpoch == epoch &&
            s.work.selected == task && s.work.task?.id == task && s.work.task?.revision == revision)
        return api ?: error("Connection unavailable")
    }

    suspend fun workAccountGrants(task: String, revision: Int, epoch: Long): List<AccountReadGrant> {
        val connection = accountReadConnection(task, revision, epoch)
        val result = accountReadGrants(connection.accountReadRequest(task), revision)
        check(accountReadConnection(task, revision, epoch) === connection)
        return result
    }

    suspend fun readWorkAccountGrant(task: String, revision: Int, epoch: Long, grant: String): AccountReadPage {
        val connection = accountReadConnection(task, revision, epoch)
        val result = accountReadPage(connection.accountReadRequest(task, grant))
        check(accountReadConnection(task, revision, epoch) === connection)
        return result
    }

    fun selectWork(id: String?) {
        workSourceEpoch++
        updateWork { it.copy(selected = id, task = null, files = emptyList(), steps = emptyList(),
            receipts = emptyList(), artifacts = emptyList(), buildLimit = 50, buildMore = false, buildDetail = "", pickingSource = false,
            sources = emptyList(), sourcesMore = false, sourceLimit = 50, excerpt = null, sourceLoading = false,
            extraReferences = "", retrySources = false,
            note = "", editModel = "", editWeb = "", editRevision = null, pendingSourceChange = null, error = null, notice = null) }
        preferences.edit().apply { if(id == null) remove("${api?.origin}:work") else putString("${api?.origin}:work", id) }.apply()
    }

    private fun acceptWork(task: WorkTask) {
        updateWork { if(it.selected != task.id || (it.task?.revision ?: 0) > task.revision) it else it.copy(task = task) }
    }

    suspend fun refreshWork() {
        val connection = api ?: return
        val selected = state.value.work.selected
        val limit = state.value.work.limit
        val rows = mutableListOf<WorkTask>()
        for (offset in 0 until limit step 50) {
            val array = JSONArray(connection.request("/v1/work/tasks?limit=50&offset=$offset"))
            repeat(array.length()) { rows.add(workTask(array.getJSONObject(it))) }
            if(array.length() < 50) break
        }
        if (api !== connection) return
        updateWork { it.copy(tasks = rows, more = rows.size >= limit) }
        if (selected != null) {
            val task = workTask(JSONObject(connection.request("/v1/work/tasks/${workTaskId(selected)}")))
            val f = JSONArray(connection.request("/v1/work/tasks/$selected/files"))
            val steps = JSONArray(connection.request("/v1/work/tasks/$selected/steps?after=${maxOf(0, task.step - 100)}&limit=100"))
            val receipts = mutableListOf<WorkReceipt>()
            val artifacts = mutableListOf<WorkArtifact>()
            val buildLimit = state.value.work.buildLimit
            if(task.target != "source") for(offset in 0 until buildLimit step 50) {
                val rr = JSONArray(connection.request("/v1/work/tasks/$selected/executions?limit=50&offset=$offset"))
                val aa = JSONArray(connection.request("/v1/work/tasks/$selected/artifacts?limit=50&offset=$offset"))
                repeat(rr.length()) { rr.getJSONObject(it).let { r -> receipts.add(WorkReceipt(r.getString("id"), r.getInt("step"), r.getString("status"), r.getString("snapshot_sha256"), r.optInt("cleanup_pending") != 0)) } }
                repeat(aa.length()) { aa.getJSONObject(it).let { a -> artifacts.add(WorkArtifact(a.getString("id"), a.getString("execution_id"), a.getString("path"), a.getInt("bytes"), a.getString("sha256"))) } }
                if(rr.length() < 50 && aa.length() < 50) break
            }
            val sources = mutableListOf<WorkSource>()
            val sourceLimit = state.value.work.sourceLimit
            for (offset in 0 until (if(task.referencesAvailable) sourceLimit else 0) step 50) {
                val batch = JSONArray(connection.request("/v1/work/tasks/$selected/sources?limit=50&offset=$offset"))
                repeat(batch.length()) { sources.add(workSource(batch.getJSONObject(it))) }
                if(batch.length() < 50) break
            }
            if (api !== connection || state.value.work.selected != selected) return
            if(state.value.work.task?.revision != task.revision) closeWorkSource()
            acceptWork(task)
            updateWork { it.copy(receipts = receipts, artifacts = artifacts, buildMore = receipts.size >= buildLimit || artifacts.size >= buildLimit, sources = sources, sourcesMore = sources.size >= sourceLimit,
                files = List(f.length()) { i -> f.getJSONObject(i).let { file ->
                WorkFile(file.getString("path"), file.getInt("bytes"), file.getString("sha256"), file.getInt("revision")) } },
                steps = List(steps.length()) { i -> steps.getJSONObject(i).let { row ->
                    val action = row.getJSONObject("action")
                    WorkStep(row.getInt("step"), action.optString("tool", "invalid action"),
                        action.optString("summary"), JSONObject().put("action", action).put("result", row.get("result")).toString(2)) } }) }
        }
    }

    suspend fun observeWork() {
        while (currentCoroutineContext().isActive && state.value.connected && state.value.page == "work") {
            try { refreshWork() }
            catch (e: CancellationException) { throw e }
            catch (e: Exception) { updateWork { it.copy(error = e.message ?: "Work connection unavailable") } }
            delay(1500)
        }
    }

    fun loadMoreWork() { updateWork { it.copy(limit = it.limit + 50) }; refreshWorkNow() }
    fun refreshWorkNow() { action { refreshWork() } }
    fun moreWorkSources() { updateWork { it.copy(sourceLimit = it.sourceLimit + 50) }; refreshWorkNow() }
    fun clearSourceChange() { updateWork { it.copy(pendingSourceChange = null, error = null) }; refreshWorkNow() }
    fun changeWorkSource(source: String, operation: String) {
        val task = state.value.work.task ?: return
        if(!source.matches(Regex("S[1-9][0-9]*")) || operation !in listOf("refresh", "remove")) return
        val pending = state.value.work.pendingSourceChange
        if(pending != null && (pending.task != task.id || pending.source != source || pending.action != operation)) return
        val request = pending ?: SourceChange(task.id, source, operation, task.revision, java.util.UUID.randomUUID().toString())
        closeWorkSource()
        updateWork { it.copy(pendingSourceChange = request) }
        mutateWork { connection ->
            val response = connection.request("/v1/work/tasks/${workTaskId(request.task)}/sources/${request.source}/actions", "POST",
                JSONObject().put("action", request.action).put("revision", request.revision).put("request_id", request.requestId))
            if(api === connection && state.value.work.selected == request.task) {
                acceptWork(workTask(JSONObject(response)))
                updateWork { it.copy(pendingSourceChange = null) }
            }
        }
    }
    fun closeWorkSource() { workSourceEpoch++; updateWork { it.copy(excerpt = null, sourceLoading = false) } }
    fun readWorkSource(source: String, offset: Int = 0) {
        val connection = api ?: return
        val selected = state.value.work.selected ?: return
        if(!source.matches(Regex("S[1-9][0-9]*")) || offset < 0) return
        val epoch = ++workSourceEpoch
        updateWork { it.copy(sourceLoading = true, error = null) }
        viewModelScope.launch {
            try {
                val j = JSONObject(connection.request("/v1/work/tasks/${workTaskId(selected)}/sources/$source?offset=$offset"))
                check(!j.has("error")) { "This source has no saved text yet." }
                if(api === connection && state.value.work.selected == selected && epoch == workSourceEpoch)
                    updateWork { it.copy(excerpt = WorkExcerpt(source, j.getString("title"), j.getString("text"),
                        j.getInt("offset"), j.getInt("next_offset"), j.getInt("characters"))) }
            } catch(e: CancellationException) { throw e }
            catch(e: Exception) { if(api === connection && epoch == workSourceEpoch) updateWork { it.copy(error = e.message ?: "Saved source unavailable") } }
            finally { if(api === connection && epoch == workSourceEpoch) updateWork { it.copy(sourceLoading = false) } }
        }
    }
    private suspend fun requireWorkReferences(connection: Api) {
        val cap = JSONObject(connection.request("/v1/capabilities"))
        check(cap.optJSONObject("work")?.optBoolean("reference_sources") == true) {
            "Work reference sources require PC backend 0.3.0.dev9 or newer."
        }
    }

    private fun mutateWork(block: suspend (Api) -> Unit) {
        if (state.value.work.busy) return
        val connection = api ?: return
        updateWork { it.copy(busy = true, error = null, notice = null) }
        viewModelScope.launch {
            try { block(connection) }
            catch(e: CancellationException) { throw e }
            catch(e: Exception) { if(api === connection) updateWork { it.copy(error = (e.message ?: "Work operation failed") + " Check refreshed task state before retrying.") } }
            finally { if(api === connection) { updateWork { it.copy(busy = false) }; try { refreshWork() } catch(_: Exception) { /* Next visible poll reports connection errors. */ } } }
        }
    }

    fun addWorkSource(uri: android.net.Uri, expectedOrigin: String) {
        val connection = api ?: return
        if(connection.origin != expectedOrigin || state.value.work.selected != null || state.value.work.busy || state.value.work.pickingSource) return
        val own = workSourceEpoch
        updateWork { it.copy(pickingSource = true, error = null) }
        viewModelScope.launch {
            try {
                val file = uploadWorkFile(getApplication<Application>(), connection, uri) { progress ->
                    if(api === connection && own == workSourceEpoch) updateWork { it.copy(notice = progress) }
                }
                if(api !== connection || own != workSourceEpoch || state.value.work.selected != null) return@launch
                val files = state.value.work.sourceFiles + file
                require(files.size <= 4 && files.sumOf { it.uploadBytes } <= 512L * 1024 * 1024) { "Up to four files and 512 MiB total." }
                require(files.map { it.name.lowercase() }.toSet().size == files.size) { "Choose distinct source filenames." }
                workRequestId = null
                updateWork { it.copy(sourceFiles = files) }
            } catch(e: CancellationException) { throw e }
            catch(e: Exception) { if(api === connection && own == workSourceEpoch) updateWork { it.copy(error = e.message ?: "Unable to read source file") } }
            finally { if(api === connection && own == workSourceEpoch) updateWork { it.copy(pickingSource = false) } }
        }
    }
    fun removeWorkSource(index: Int) {
        if(state.value.work.busy || state.value.work.pickingSource) return
        workRequestId = null
        updateWork { it.copy(sourceFiles = it.sourceFiles.filterIndexed { i, _ -> i != index }) }
    }

    fun createWork() {
        val w = state.value.work
        if(w.requirements.isBlank() || w.busy || w.pickingSource || state.value.model.isBlank()) return
        if(workRequestId == null) workRequestId = UUID.randomUUID().toString()
        val request = workRequestId
        val model = state.value.model
        val effort = state.value.effort
        val webMode = state.value.webMode
        mutateWork { connection ->
            val urls = researchUrls(true, w.references)
            if(urls.isNotEmpty()) requireWorkReferences(connection)
            if(w.publicQuery.isNotBlank() || w.followLinks) {
                val cap = JSONObject(connection.request("/v1/capabilities"))
                check(cap.optJSONObject("work")?.optBoolean("public_query_and_links") == true) { "Update the PC backend for Work web research." }
            }
            val task = workTask(JSONObject(connection.request("/v1/work/tasks", "POST", JSONObject()
                .put("title", w.title.trim().ifBlank { w.requirements.trim().lineSequence().first().take(90) }).put("requirements", w.requirements.trim()).put("build_target", w.target)
                .put("start", true).put("reasoning_effort", effort).put("web_mode", if(w.sourceFiles.isNotEmpty() && webMode != "on") "off" else webMode)
                .apply { if(w.sourceFiles.isNotEmpty()) put("upload_ids", JSONArray(w.sourceFiles.mapNotNull { it.uploadId })); put("source_files", attachmentJson(w.sourceFiles.filter { it.uploadId == null })) }
                .apply { if(urls.isNotEmpty()) put("reference_urls", JSONArray(urls)) }
                .apply { if(w.publicQuery.isNotBlank() || w.followLinks) { put("public_query", w.publicQuery.trim().ifBlank { null } ?: JSONObject.NULL); put("follow_links", w.followLinks) } }
                .put("model_id", model.ifBlank { null } ?: JSONObject.NULL).put("request_id", request))))
            if(api === connection) { workRequestId = null; updateWork { it.copy(title = "", requirements = "", references = "", publicQuery = "", followLinks = false, sourceFiles = emptyList()) }; selectWork(task.id); acceptWork(task) }
        }
    }

    fun transitionWork(action: String) {
        val task = state.value.work.task ?: return
        mutateWork { connection ->
            val updated = workTask(JSONObject(connection.request("/v1/work/tasks/${task.id}/actions", "POST",
                JSONObject().put("action", action).put("revision", task.revision))))
            if(api === connection) acceptWork(updated)
        }
    }

    fun reviseWork(resume: Boolean = false) {
        val w = state.value.work; val task = w.task ?: return
        if(w.note.isBlank() && w.editModel.isBlank() && w.editWeb.isBlank() && w.extraReferences.isBlank() && !w.retrySources) return
        mutateWork { connection ->
            val urls = researchUrls(true, w.extraReferences)
            if(urls.isNotEmpty() || w.retrySources) requireWorkReferences(connection)
            val body = JSONObject().put("revision", w.editRevision ?: task.revision)
                .apply { if(resume) put("resume", true).put("reasoning_effort", state.value.effort).put("model_id", state.value.model) }
                .apply {
                    if(urls.isNotEmpty()) put("reference_urls", JSONArray(urls))
                    if(w.retrySources) put("retry_sources", true)
                }
            if(w.note.isNotBlank()) body.put("note", w.note.trim())
            if(w.editModel.isNotBlank()) body.put("model_id", w.editModel)
            if(w.editWeb.isNotBlank()) body.put("web_mode", w.editWeb)
            val updated = workTask(JSONObject(connection.request("/v1/work/tasks/${task.id}", "PATCH", body)))
            if(api === connection && state.value.work.selected == task.id) { acceptWork(updated); updateWork { it.copy(note = "", editModel = "", editWeb = "", extraReferences = "", retrySources = false, editRevision = null) } }
        }
    }

    fun clearWorkEdit() {
        updateWork { it.copy(note = "", editModel = "", editWeb = "", extraReferences = "", retrySources = false, editRevision = null, error = null) }
        refreshWorkNow()
    }

    fun moreBuildEvidence() { updateWork { it.copy(buildLimit = it.buildLimit + 50) }; refreshWorkNow() }
    fun readBuildReceipt(id: String) {
        val selected = state.value.work.selected ?: return
        mutateWork { connection ->
            val detail = JSONObject(connection.request("/v1/work/tasks/${workTaskId(selected)}/executions/${workTaskId(id)}")).toString(2)
            if(api === connection && state.value.work.selected == selected) updateWork { it.copy(buildDetail = detail) }
        }
    }
    fun saveWorkArtifact(task: String, artifact: WorkArtifact, expectedOrigin: String, uri: android.net.Uri) {
        if(api?.origin != expectedOrigin) { updateWork { it.copy(error = "Connection changed. Select the artifact again.") }; return }
        mutateWork { connection ->
            val bytes = connection.downloadArtifact(task, artifact)
            withContext(Dispatchers.IO) {
                getApplication<Application>().contentResolver.openOutputStream(uri)?.use { it.write(bytes) }
                    ?: error("Unable to save artifact")
            }
            if(api === connection) updateWork { it.copy(notice = "Artifact verified and saved. It has not been installed or run.") }
        }
    }

    fun saveWorkExport(id: String, expectedOrigin: String, uri: android.net.Uri) {
        if(api?.origin != expectedOrigin) { updateWork { it.copy(error = "Connection changed. Select the source export again.") }; return }
        mutateWork { connection ->
            val bytes = connection.downloadWork(id)
            withContext(Dispatchers.IO) {
                getApplication<Application>().contentResolver.openOutputStream(uri)?.use { it.write(bytes) }
                    ?: error("Unable to save source archive")
            }
            if(api === connection) updateWork { it.copy(notice = "Source archive saved. Generated code has not been built or tested.") }
        }
    }

    suspend fun recallRequest(path: String, method: String = "GET", body: JSONObject? = null): String {
        val connection = api ?: error("Connect first")
        val result = connection.request(path, method, body)
        check(api === connection) { "Connection changed. Reopen History and retrieval." }
        return result
    }

    private fun updateMemory(change: (MemoryUi) -> MemoryUi) { mutable.update { it.copy(memory = change(it.memory)) } }

    suspend fun refreshMemories(append: Boolean = false) {
        val connection = api ?: return
        val own = ++memoryEpoch
        val m = state.value.memory
        try {
            if(!m.ready) {
                val cap = JSONObject(connection.request("/v1/capabilities"))
                check(cap.getJSONObject("memory").optBoolean("creation_retries")) { "Update the PC backend to 0.3.0.dev6 for memory controls." }
                if(api !== connection || own != memoryEpoch) return
                val p = cap.getJSONObject("permissions")
                updateMemory { it.copy(ready = true, personalAllowed = p.optBoolean("chat"), projectAllowed = p.optBoolean("work")) }
                if(p.optBoolean("work")) loadMemoryProjects()
            }
            val project = if(m.scope.isEmpty()) "" else "&task_id=${workTaskId(m.scope)}"
            val query = URLEncoder.encode(m.query, "UTF-8")
            val rows = JSONArray(connection.request("/v1/memories?q=$query&limit=50&offset=${if(append) m.rows.size else 0}$project"))
            if(api !== connection || own != memoryEpoch) return
            val batch = List(rows.length()) { memoryEntry(rows.getJSONObject(it)) }
            updateMemory { it.copy(rows = if(append) it.rows + batch else batch, more = batch.size == 50) }
        } catch(e: CancellationException) { throw e }
        catch(e: Exception) { if(api === connection && own == memoryEpoch) updateMemory { it.copy(error = if(!it.ready) (e.message ?: "Connection unavailable") + ". Memory controls require backend 0.3.0.dev6 or newer. Check the connection and backend version." else e.message ?: "Memory connection unavailable") } }
    }

    suspend fun loadMemoryProjects(append: Boolean = false) {
        val connection = api ?: return
        val offset = if(append) state.value.memory.projects.size else 0
        val rows = JSONArray(connection.request("/v1/work/tasks?limit=50&offset=$offset"))
        if(api !== connection) return
        val batch = List(rows.length()) { rows.getJSONObject(it).let { j -> MemoryProject(j.getString("id"), j.getString("title")) } }
        updateMemory { it.copy(projects = if(append) it.projects + batch else batch, projectsMore = batch.size == 50) }
    }
    fun moreMemoryProjects() { action { loadMemoryProjects(true) } }
    suspend fun refreshMemoryPage() {
        try {
            if(state.value.memory.ready && state.value.memory.projectAllowed) loadMemoryProjects()
            refreshMemories()
        } catch(e: CancellationException) { throw e }
        catch(e: Exception) { updateMemory { it.copy(error = e.message ?: "Memory connection unavailable") } }
    }
    fun refreshMemoryPageNow() { action { refreshMemoryPage() } }
    fun refreshMemoryNow(append: Boolean = false) { action { refreshMemories(append) } }
    fun selectMemoryScope(id: String, title: String) {
        if(state.value.memory.editor || state.value.memory.busy) return
        memoryEpoch++
        updateMemory { it.copy(scope = id, scopeTitle = title, query = "", rows = emptyList(), error = null, notice = null) }
        refreshMemoryNow()
    }
    fun queryMemory(value: String) {
        if(state.value.memory.editor) return
        memoryEpoch++; memorySearch?.cancel()
        updateMemory { it.copy(query = value.take(1000)) }
        memorySearch = viewModelScope.launch { delay(250); refreshMemories() }
    }
    fun editMemory(row: MemoryEntry?) {
        if(state.value.memory.busy) return
        memoryRequestId = null
        updateMemory { it.copy(editor = true, editing = row, title = row?.title ?: "", content = row?.content ?: "", error = null, notice = null) }
    }
    fun cancelMemoryEdit() { memoryRequestId = null; updateMemory { it.copy(editor = false, editing = null, error = null) } }
    fun changeMemory(field: String, value: String) {
        if(state.value.memory.busy) return
        memoryRequestId = null
        updateMemory { if(field == "title") it.copy(title = value.take(200)) else it.copy(content = value.take(8000)) }
    }
    fun confirmMemoryDelete(row: MemoryEntry?) { if(!state.value.memory.busy) updateMemory { it.copy(deleting = row, error = null, notice = null) } }
    private fun mutateMemory(block: suspend (Api) -> Unit) {
        if(state.value.memory.busy) return
        val connection = api ?: return
        updateMemory { it.copy(busy = true, error = null, notice = null) }
        viewModelScope.launch {
            try { block(connection) }
            catch(e: CancellationException) { throw e }
            catch(e: Exception) { if(api === connection) updateMemory { it.copy(error = (e.message ?: "Memory operation failed") + " Review refreshed records before retrying. Cancel and reopen an editor after a conflict.") } }
            finally { if(api === connection) { updateMemory { it.copy(busy = false) }; refreshMemories() } }
        }
    }
    fun saveMemory() {
        val m = state.value.memory
        if(!m.ready || m.title.isBlank() || m.content.isBlank()) return
        if(m.editing == null && memoryRequestId == null) memoryRequestId = UUID.randomUUID().toString()
        val request = memoryRequestId
        mutateMemory { connection ->
            val body = JSONObject().put("title", m.title.trim()).put("content", m.content.trim())
            if(m.editing != null) connection.request("/v1/memories/${m.editing.id}", "PATCH", body.put("revision", m.editing.revision))
            else connection.request("/v1/memories", "POST", body.put("request_id", request).put("task_id", m.scope.ifBlank { null } ?: JSONObject.NULL))
            if(api === connection) { memoryRequestId = null; updateMemory { it.copy(editor = false, editing = null, query = "", notice = "Memory saved.") } }
        }
    }
    fun deleteMemory() {
        val row = state.value.memory.deleting ?: return
        mutateMemory { connection ->
            try { connection.request("/v1/memories/${row.id}?revision=${row.revision}", "DELETE")
                if(api === connection) updateMemory { it.copy(notice = "Memory deleted from future retrieval. Existing chats and backups remain.") }
            } finally { if(api === connection) updateMemory { it.copy(deleting = null) } }
        }
    }
    fun saveMemoryExport(scope: String, expectedOrigin: String, uri: android.net.Uri) {
        if(api?.origin != expectedOrigin) { updateMemory { it.copy(error = "Connection changed. Select memory export again.") }; return }
        mutateMemory { connection ->
            val bytes = connection.downloadMemory(scope.ifBlank { null })
            withContext(Dispatchers.IO) {
                getApplication<Application>().contentResolver.openOutputStream(uri)?.use { it.write(bytes) } ?: error("Unable to save memory export")
            }
            if(api === connection) updateMemory { it.copy(notice = "Memory scope exported.") }
        }
    }

    suspend fun refreshDevice() {
        val connection = api ?: return
        mutable.update { it.copy(device = it.device.copy(loading = true, error = null)) }
        try {
            val j = JSONObject(connection.request("/v1/device"))
            val scopes = j.getJSONArray("scopes")
            val identity = DeviceIdentity(j.getString("id"), j.getString("name"), j.getString("role"), j.getString("created_at"), List(scopes.length()) { scopes.getString(it) })
            if(api === connection) mutable.update { it.copy(device = DeviceUi(identity = identity)) }
        } catch(e: CancellationException) { throw e }
        catch(e: Exception) { if(api === connection) mutable.update { it.copy(device = DeviceUi(error = (e.message ?: "Connection unavailable") + " Permission details require backend 0.3.0.dev8 or newer.")) } }
        finally { if(api === connection) mutable.update { it.copy(device = it.device.copy(loading = false)) } }
    }
    fun refreshDeviceNow() { action { refreshDevice() } }

    fun disconnect() {
        action {
            vault.clear()
            api = null
            modelManagement.reset()
            workRequestId = null
            memoryRequestId = null
            memoryEpoch++
            memorySearch?.cancel()
            mutable.value = State(connectionEpoch = state.value.connectionEpoch + 1)
        }
    }
}

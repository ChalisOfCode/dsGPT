package com.dsgpt.mobile

import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import org.json.JSONArray
import org.json.JSONObject

data class ModelAsset(val id: String, val name: String, val kind: String, val size: Long,
    val license: String, val source: String, val sha256: String, val purpose: String)
data class ModelDownload(val id: String, val asset: String, val status: String, val downloaded: Long,
    val total: Long, val error: String?) {
    val resumable get() = status in listOf("paused", "cancelled", "failed")
    val removable get() = resumable || status == "downloaded"
    val pausable get() = status in listOf("queued", "downloading", "verifying")
    val cancellable get() = pausable || status in listOf("paused", "failed")
}
data class ModelRuntime(val id: String, val platform: String, val supported: Boolean,
    val installed: Boolean, val assets: List<String>)
data class RegisteredModel(val id: String, val label: String, val runtime: String, val context: Int,
    val output: Int, val managed: Boolean, val configurationOwned: Boolean)
data class ModelRemoval(val title: String, val detail: String, val path: String)
data class ModelForm(val id: String = "", val name: String = "", val asset: String = "", val runtime: String = "",
    val context: String = "4096", val output: String = "1024", val gpu: String = "0",
    val external: Boolean = false, val engine: String = "ollama", val endpoint: String = "http://127.0.0.1:11434",
    val runtimeModel: String = "", val abliterated: Boolean = false) {
    fun validNumbers() = (context.toIntOrNull() ?: 0) in 512..131072 &&
        (output.toIntOrNull() ?: 0) in 1 until (context.toIntOrNull() ?: 0) &&
        (external || (gpu.toIntOrNull() ?: -1) in 0..999)
    fun validIdentity() = id.matches(Regex("[A-Za-z0-9][A-Za-z0-9_.-]{0,99}")) && name.trim().isNotEmpty() && name.length <= 200
}
data class ModelsUi(val allowed: Boolean? = null, val tab: String = "library",
    val assets: List<ModelAsset> = emptyList(), val downloads: List<ModelDownload> = emptyList(),
    val runtimes: List<ModelRuntime> = emptyList(), val models: List<RegisteredModel> = emptyList(),
    val runtimeState: String = "unknown", val activeModel: String? = null, val runtimeBusy: Boolean = false,
    val runtimeError: String? = null, val busy: Boolean = false, val error: String? = null,
    val notice: String? = null, val removal: ModelRemoval? = null, val form: ModelForm = ModelForm()) {
    fun downloaded(id: String) = downloads.any { it.asset == id && it.status == "downloaded" }
    fun canRegister() = form.validIdentity() && form.validNumbers() && if(form.external) form.runtimeModel.isNotBlank()
        else downloaded(form.asset) && runtimes.any { it.id == form.runtime && it.installed && it.supported }
}

private fun <T> parseList(raw: String, parse: (JSONObject) -> T): List<T> = JSONArray(raw).let { rows -> List(rows.length()) { parse(rows.getJSONObject(it)) } }
private fun JSONObject.nullable(key: String): String? = if(isNull(key)) null else optString(key).ifBlank { null }

/** Operations belong to the app's ViewModel, so navigating away does not replay a mutation. */
class ModelManager(private val scope: CoroutineScope, private val connection: () -> Api?,
    private val onModels: (List<Model>) -> Unit) {
    private val mutable = MutableStateFlow(ModelsUi())
    val state = mutable.asStateFlow()
    private var epoch = 0
    fun reset() { epoch++; mutable.value = ModelsUi() }
    fun tab(value: String) { mutable.update { it.copy(tab = value) } }
    fun edit(change: (ModelForm) -> ModelForm) { if(!state.value.busy) mutable.update { it.copy(form = change(it.form)) } }
    fun removal(value: ModelRemoval?) { if(!state.value.busy) mutable.update { it.copy(removal = value) } }
    fun dismissError() { mutable.update { it.copy(error = null) } }
    suspend fun observe() { while(currentCoroutineContext().isActive) { refresh(); delay(2000) } }
    fun refreshNow() { dismissError(); scope.launch { refresh() } }
    private suspend fun refresh() {
        if(state.value.busy) return
        val api = connection() ?: return
        val own = ++epoch
        try {
            val cap = JSONObject(api.request("/v1/capabilities"))
            val allowed = cap.getJSONObject("permissions").optBoolean("model_management")
            if(connection() !== api || own != epoch) return
            mutable.update { it.copy(allowed = allowed) }
            if(!allowed) return
            val data = coroutineScope {
                listOf("/v1/model-catalog", "/v1/downloads", "/v1/runtimes", "/v1/models", "/v1/runtime/status")
                    .map { path -> async { api.request(path) } }.awaitAll()
            }
            if(connection() !== api || own != epoch || state.value.busy) return
            val assets = parseList(data[0]) { j -> ModelAsset(j.getString("id"), j.getString("name"), j.getString("kind"), j.getLong("size"), j.getString("license"), j.getString("source"), j.getString("sha256"), j.getString("purpose")) }
            val downloads = parseList(data[1]) { j -> ModelDownload(j.getString("id"), j.getString("asset_id"), j.getString("status"), j.getLong("downloaded"), j.getLong("total"), j.nullable("error_code")) }
            val runtimes = parseList(data[2]) { j -> ModelRuntime(j.getString("id"), j.getString("platform"), j.getBoolean("supported_here"), j.getBoolean("installed"), j.getJSONArray("assets").let { a -> List(a.length()) { a.getString(it) } }) }
            val models = parseList(data[3]) { j -> RegisteredModel(j.getString("id"), j.getString("label"), j.getString("runtime"), j.getInt("context"), j.getInt("output_tokens"), j.getBoolean("managed"), j.optBoolean("configuration_owned", true)) }
            val runtime = JSONObject(data[4])
            mutable.update { it.copy(assets = assets, downloads = downloads, runtimes = runtimes, models = models,
                runtimeState = runtime.getString("state"), runtimeBusy = runtime.getBoolean("busy"), activeModel = runtime.nullable("model_id"), runtimeError = runtime.nullable("error_code")) }
            onModels(models.map { Model(it.id, it.label) })
        } catch(e: CancellationException) { throw e }
        catch(e: Exception) { if(connection() === api && own == epoch) mutable.update { it.copy(error = e.message ?: "Model management unavailable. Check the PC connection and backend version.") } }
    }
    fun mutate(path: String, method: String = "POST", body: JSONObject? = null, notice: String = "Updated. Review the current state below.") {
        if(state.value.busy || state.value.allowed != true) return
        val api = connection() ?: return
        epoch++
        mutable.update { it.copy(busy = true, error = null, notice = null) }
        scope.launch {
            try { api.request(path, method, body); if(connection() === api) mutable.update { it.copy(notice = notice) } }
            catch(e: CancellationException) { throw e }
            catch(e: Exception) { if(connection() === api) mutable.update { it.copy(error = (e.message ?: "Change failed") + " Check refreshed state before retrying. Downloads must finish before installation; forget registrations before removing their files.") } }
            finally { if(connection() === api) { mutable.update { it.copy(busy = false, removal = null) }; refresh() } }
        }
    }
    fun download(id: String) = mutate("/v1/downloads", body = JSONObject().put("asset_id", id), notice = "Download queued on your PC. It continues when this screen closes.")
    fun downloadAction(id: String, action: String) = mutate("/v1/downloads/$id/actions", body = JSONObject().put("action", action), notice = if(action == "cancel") "Download cancelled. Partial files remain until removed." else "Download updated.")
    fun confirmRemoval() { state.value.removal?.let { mutate(it.path, "DELETE") } }
    fun register() {
        val s = state.value; val f = s.form
        if(!s.canRegister()) return
        val body = JSONObject().put("id", f.id).put("name", f.name.trim()).put("context", f.context.toInt()).put("output_tokens", f.output.toInt())
        if(f.external) body.put("runtime", f.engine).put("endpoint", f.endpoint).put("runtime_model", f.runtimeModel).put("abliterated", f.abliterated)
        else body.put("asset_id", f.asset).put("runtime_id", f.runtime).put("gpu_layers", f.gpu.toInt())
        mutate(if(f.external) "/v1/models/register" else "/v1/models/managed", body = body,
            notice = "Model added to Chat and Work. Loading is checked on first use.")
    }
}

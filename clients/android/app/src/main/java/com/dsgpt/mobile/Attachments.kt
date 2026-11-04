package com.dsgpt.mobile

import android.content.ContentResolver
import android.net.Uri
import android.provider.OpenableColumns
import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction
import org.json.JSONArray
import org.json.JSONObject

private val attachmentExtensions = "txt md markdown rst csv tsv json jsonl yaml yml toml ini xml py js jsx ts tsx css html htm rs kt kts java go rb php c h cpp hpp cs swift sql sh ps1 log tex".split(" ").toSet()
data class DraftAttachment(val name: String, val text: String, val originalBase64: String? = null, val documentNotice: String? = null, val uploadId: String? = null, val uploadBytes: Long = 0)
data class AttachmentRecord(val id: String, val name: String, val bytes: Int, val sha256: String, val created: String, val removed: Boolean, val documentNotice: String? = null)
data class AttachmentPage(val chatId: String, val file: AttachmentRecord, val text: String? = null, val offset: Int = 0, val next: Int? = null, val total: Int = 0, val loading: Boolean = false, val error: String? = null, val notice: String? = null)
fun validateAttachments(files: List<DraftAttachment>) {
    require(files.size <= 4) { "Use up to four text files per message." }
    var total = 0
    var originals = 0
    files.forEach { file ->
        val stem = file.name.substringBefore('.').uppercase()
        require(file.name.isNotEmpty() && file.name.length <= 160 && file.name.lastIndexOf('.') > 0 &&
            file.name.none { it.code < 32 || it.code == 127 || it in "\\/<>:\"|?*" } &&
            !file.name.endsWith(' ') && !file.name.endsWith('.') &&
            !stem.matches(Regex("CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]")) &&
            (if(file.originalBase64 != null) file.name.substringAfterLast('.').lowercase() in setOf("docx", "pdf", "png", "jpg", "jpeg", "webp", "xlsx", "pptx", "zip") else file.name.substringAfterLast('.').lowercase() in attachmentExtensions)) { "Choose a supported text/code file with a portable filename." }
        require(file.text.none { it.code < 32 && it !in "\t\r\n" }) { "Binary/control data is not supported." }
        file.originalBase64?.let { encoded ->
            val bytes = encoded.length / 4 * 3 - encoded.takeLast(2).count { it == '=' }
            originals += bytes
            require(bytes <= 524288 && originals <= 786432) { "DOCX: 512 KiB each, 768 KiB total." }
        }
        val size = file.text.toByteArray(Charsets.UTF_8).size; total += size
        require(size <= 65536 && total <= 131072) { "Text files are limited to 64 KiB each and 128 KiB per message." }
    }
}
fun decodeAttachment(name: String, bytes: ByteArray): DraftAttachment {
    require(bytes.size <= 65536) { "Choose a text file no larger than 64 KiB." }
    val text = try { Charsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString() }
        catch(e: java.nio.charset.CharacterCodingException) { throw IllegalArgumentException("Choose a valid UTF-8 text file.", e) }
    return DraftAttachment(name, text).also { validateAttachments(listOf(it)) }
}
fun readAttachment(resolver: ContentResolver, uri: Uri, allowDocx: Boolean = false, allowZip: Boolean = false): DraftAttachment {
    val name = resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { cursor ->
        require(cursor.moveToFirst()) { "Unable to inspect selected file." }; cursor.getString(0)
    } ?: error("Unable to inspect selected filename.")
    val document = allowDocx && (name.substringAfterLast('.').lowercase() in setOf("docx", "pdf", "png", "jpg", "jpeg", "webp", "xlsx", "pptx") || (allowZip && name.endsWith(".zip", ignoreCase = true)))
    val limit = if(document) 524288 else 65536
    val result = java.io.ByteArrayOutputStream()
    (resolver.openInputStream(uri) ?: error("Unable to read selected file.")).use { input ->
        val buffer = ByteArray(8192)
        while(true) { val count = input.read(buffer); if(count < 0) break
            require(result.size() + count <= limit) { "Choose a text file no larger than 64 KiB." }
            result.write(buffer, 0, count)
        }
    }
    if(document) return DraftAttachment(name, "", android.util.Base64.encodeToString(result.toByteArray(), android.util.Base64.NO_WRAP))
    return decodeAttachment(name, result.toByteArray())
}
fun attachmentJson(files: List<DraftAttachment>) = JSONArray().apply {
    files.forEach { file -> put(JSONObject().put("name", file.name).apply { if(file.originalBase64 != null) put("original_base64", file.originalBase64) else put("text", file.text) }) }
}
fun attachmentRecords(rows: JSONArray?) = if(rows == null) emptyList() else List(rows.length()) { i ->
    val row = rows.getJSONObject(i)
    AttachmentRecord(row.getString("id"), row.getString("name"), row.getInt("bytes"), row.getString("sha256"), row.getString("created_at"), row.optBoolean("removed"), row.optJSONObject("document")?.optString("notice"))
}

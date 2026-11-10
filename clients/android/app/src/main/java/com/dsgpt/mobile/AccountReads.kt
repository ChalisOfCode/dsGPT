package com.dsgpt.mobile

import java.io.InputStream
import java.time.Instant
import okhttp3.HttpUrl.Companion.toHttpUrl
import org.json.JSONArray
import org.json.JSONObject

// These values live only in the private view. Never put them in WorkState or exports.
class AccountReadGrant(val id: String, val label: String, val origin: String,
    val path: String, val expiresAt: Double)
class AccountReadPage(val text: String, val truncated: Boolean)

internal const val ACCOUNT_RESPONSE_BYTES = 256 * 1024

internal fun boundedAccountBody(input: InputStream): String {
    val bytes = java.io.ByteArrayOutputStream()
    val buffer = ByteArray(4096)
    while (true) {
        val count = input.read(buffer)
        if (count < 0) break
        check(bytes.size() + count <= ACCOUNT_RESPONSE_BYTES) { "Private response exceeds limit" }
        bytes.write(buffer, 0, count)
    }
    return bytes.toString("UTF-8")
}

private fun JSONObject.accountString(name: String, limit: Int): String {
    val value = get(name)
    require(value is String && value.codePointCount(0, value.length) <= limit)
    return value
}

private fun JSONObject.accountLong(name: String): Long {
    val value = get(name)
    require(value is Int || value is Long)
    return (value as Number).toLong()
}

internal fun accountReadGrants(raw: String, revision: Int,
    now: Long = Instant.now().epochSecond): List<AccountReadGrant> {
    val rows = JSONArray(raw)
    require(rows.length() <= 64)
    val seen = mutableSetOf<String>()
    return List(rows.length()) { index ->
        val row = rows.getJSONObject(index)
        val id = workTaskId(row.accountString("id", 36))
        require(seen.add(id))
        val label = row.accountString("label", 80)
        require(label.isNotBlank() && label.none { it.code < 32 })
        val origin = row.accountString("origin", 2048)
        val url = origin.toHttpUrl()
        require(url.isHttps && url.username.isEmpty() && url.password.isEmpty() &&
            url.encodedPath == "/" && url.query == null && url.fragment == null)
        val path = row.accountString("read_path", 1001)
        require(path.matches(Regex("/[A-Za-z0-9_./~-]{0,1000}")) && !path.startsWith("//"))
        val expiry = row.get("expires_at")
        require(expiry is Number)
        val expires = expiry.toDouble()
        require(expires.isFinite() && expires > 0)
        val taskRevision = row.accountLong("task_revision")
        require(taskRevision > 0 && row.has("profile_revision"))
        require(row.isNull("profile_revision") || row.accountLong("profile_revision") > 0)
        if (taskRevision == revision.toLong() && expires > now)
            AccountReadGrant(id, label, origin, path, expires) else null
    }.filterNotNull()
}

internal fun accountReadPage(raw: String): AccountReadPage {
    val row = JSONObject(raw)
    workTaskId(row.accountString("session_id", 36))
    val text = row.accountString("text", 12000)
    val truncated = row.get("truncated")
    require(truncated is Boolean)
    return AccountReadPage(text, truncated)
}

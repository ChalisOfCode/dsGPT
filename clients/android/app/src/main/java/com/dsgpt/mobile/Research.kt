package com.dsgpt.mobile

import okhttp3.HttpUrl.Companion.toHttpUrl

data class ResearchSource(
    val id: String,
    val url: String,
    val title: String,
    val status: String,
    val retrieved: String,
    val published: String?,
    val sha256: String,
)

fun publicSourceUrl(raw: String): String {
    require(raw.length <= 4096 && raw.none { it <= ' ' || it == '\\' }) {
        "Use a public HTTPS source URL."
    }
    val url = raw.toHttpUrl()
    require(url.isHttps && url.port == 443 && url.username.isEmpty() && url.password.isEmpty()
        && url.host.contains('.') && !url.host.endsWith('.') && !url.host.contains(':')
        && !Regex("[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+").matches(url.host)
        && listOf(".local", ".localhost", ".internal", ".invalid").none { url.host.endsWith(it) }) {
        "Use a public HTTPS domain without credentials or a custom port."
    }
    return url.toString()
}

fun researchUrls(search: Boolean, text: String): List<String> {
    val urls = text.lines().map { it.trim() }.filter { it.isNotEmpty() }.distinct()
    require(urls.size <= 6) { "Use up to six source URLs, one per line." }
    require(search || urls.isNotEmpty()) { "Add a source URL or enable configured web search." }
    urls.forEach { publicSourceUrl(it) }
    return urls
}

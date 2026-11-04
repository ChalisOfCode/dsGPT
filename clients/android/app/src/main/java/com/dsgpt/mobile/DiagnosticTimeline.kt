package com.dsgpt.mobile

import java.time.Instant

enum class DiagnosticEvent(val code: String) {
    STARTED("app_started"), BACKGROUND("app_backgrounded"), FOREGROUND("app_foregrounded"),
    NETWORK("network_unavailable"), STREAM("stream_interrupted"), CRASH("app_crash"),
    UPLOAD("upload_failed"), DOWNLOAD("download_failed"), HANDLED("handled_exception"),
    SYNC("sync_failed"), LOW_MEMORY("low_memory"), ANR("app_not_responding")
}

data class DiagnosticEntry(val event: DiagnosticEvent, val at: String, val correlationId: String? = null)

/** Only enum codes and UTC times enter this buffer; no Throwable or request contents. */
class DiagnosticTimeline(private val limit: Int = 100) {
    init { require(limit in 1..100) }
    private val entries = ArrayDeque<DiagnosticEntry>()
    @Synchronized fun record(event: DiagnosticEvent, at: String = Instant.now().toString(), correlationId: String? = null) {
        Instant.parse(at)
        val id = correlationId?.let { java.util.UUID.fromString(it).toString() }
        entries.addLast(DiagnosticEntry(event, at, id))
        while (entries.size > limit) entries.removeFirst()
    }
    @Synchronized fun snapshot(): List<DiagnosticEntry> = entries.toList()
}

package com.dsgpt.mobile

import org.junit.Assert.*
import org.junit.Test

class DiagnosticTimelineTest {
    @Test fun historyIsBoundedOrderedAndCopiesCannotChangeRetainedEvents() {
        val timeline = DiagnosticTimeline(2)
        timeline.record(DiagnosticEvent.STARTED, "2026-10-21T00:00:00Z")
        val earlier = timeline.snapshot()
        timeline.record(DiagnosticEvent.NETWORK, "2026-10-21T00:00:01Z")
        timeline.record(DiagnosticEvent.CRASH, "2026-10-21T00:00:02Z")
        assertEquals(listOf(DiagnosticEvent.NETWORK, DiagnosticEvent.CRASH), timeline.snapshot().map { it.event })
        assertEquals(listOf(DiagnosticEvent.STARTED), earlier.map { it.event })
    }
    @Test fun noArbitraryEventOrInvalidTimestampCanBeRecorded() {
        assertFalse(DiagnosticEvent.entries.any { it.code.contains("password") })
        assertThrows(java.time.format.DateTimeParseException::class.java) {
            DiagnosticTimeline().record(DiagnosticEvent.CRASH, "private exception text")
        }
        assertThrows(IllegalArgumentException::class.java) { DiagnosticTimeline(1000) }
        assertThrows(IllegalArgumentException::class.java) {
            DiagnosticTimeline().record(DiagnosticEvent.NETWORK, correlationId = "private-url")
        }
    }
}

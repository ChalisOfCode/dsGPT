package com.dsgpt.mobile

import org.junit.Assert.*
import org.junit.Test

class ResearchTest {
    @Test fun sourceLinksRefuseExecutablePrivateAndCredentialedTargets() {
        for (url in listOf("javascript:alert(1)", "file:///tmp/a", "http://example.org",
            "https://user:secret@example.org", "https://localhost", "https://127.0.0.1",
            "https://[::1]", "https://device.internal", "https://example.org:123",
            "https://example.org/\ncommand", "https://example.org\\path")) {
            assertThrows(IllegalArgumentException::class.java) { publicSourceUrl(url) }
        }
        assertEquals("https://example.org/path?q=one%20two", publicSourceUrl("https://example.org/path?q=one%20two"))
    }
    @Test fun sourceOptionsRequireInputAndBoundUniqueUrls() {
        assertThrows(IllegalArgumentException::class.java) { researchUrls(false, "") }
        assertTrue(researchUrls(true, "").isEmpty())
        assertEquals(1, researchUrls(false, "https://example.org/a\nhttps://example.org/a").size)
        assertThrows(IllegalArgumentException::class.java) {
            researchUrls(false, (0..6).joinToString("\n") { "https://example.org/$it" })
        }
    }
}

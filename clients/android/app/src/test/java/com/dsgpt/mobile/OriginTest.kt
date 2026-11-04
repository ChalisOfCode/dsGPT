package com.dsgpt.mobile

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertNull
import org.junit.Test

class OriginTest {
    @Test
    fun installerSuggestionRequiresPrivateHttpsAndDoesNotRedeemCredentials() {
        assertEquals("https://pc.tail123.ts.net:8443" to "abc_123-xyz",
            setupPairing("https://pc.tail123.ts.net:8443/", "abc_123-xyz"))
        assertNull(setupPairing("https://example.com", "abc_123-xyz"))
        assertNull(setupPairing("https://pc.tail123.ts.net", "bad code"))
        assertNull(setupPairing(null, null))
    }
    @Test
    fun allowsOnlyCredentialFreeTailnetHttpsOrigins() {
        assertEquals("https://pc.tail123.ts.net", serverOrigin("https://pc.tail123.ts.net/"))
        listOf(
                "http://pc.tail123.ts.net",
                "https://example.com",
                "https://pc.ts.net.evil.com",
                "https://u:p@pc.ts.net",
                "https://pc.ts.net/path",
                "https://pc.ts.net/?token=bad",
            )
            .forEach { assertThrows(IllegalArgumentException::class.java) { serverOrigin(it) } }
    }
}

package com.dsgpt.mobile

import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test

class AutomaticConnectionTest {
    private val origin = "https://pc.tail.ts.net:8443"
    private val id = "11111111-1111-4111-8111-111111111111"
    private data class Stored(val origin: String, val token: String)

    @Test fun workingConnectionDoesNotRedeemOrReplace() = runBlocking {
        val old = Stored(origin, "existing")
        val result = automaticConnection(origin, { old }, { it.origin }, { id },
            { error("Must not create another device") }, { error("Must not overwrite credential") })
        assertEquals(AutomaticConnectionResult("reused", id), result)
    }
    @Test fun differentDesktopIsPreservedWithoutContactingIt() = runBlocking {
        val result = automaticConnection(origin, { Stored("https://other.tail.ts.net", "existing") },
            { it.origin }, { error("Must not contact other server") },
            { error("Must not redeem") }, { error("Must not save") })
        assertEquals("different_desktop", result.status)
    }
    @Test fun offlineConnectionDoesNotCreateAnotherCredential() = runBlocking {
        var saved = false
        try {
            automaticConnection(origin, { Stored(origin, "existing") }, { it.origin },
                { throw java.io.IOException("network unavailable") },
                { error("Must not redeem on a network failure") }, { saved = true })
            fail("Network failure must propagate")
        } catch (_: java.io.IOException) { assertFalse(saved) }
    }
    @Test fun expiredConnectionIsReplacedOnlyAfterVerification() = runBlocking {
        var stored = Stored(origin, "expired")
        val events = mutableListOf<String>()
        val result = automaticConnection(origin, { stored }, { it.origin },
            { events.add("verify:" + it.token); if (it.token == "expired") null else id },
            { events.add("pair"); Stored(origin, "new") },
            { events.add("save"); stored = it })
        assertEquals(listOf("verify:expired", "pair", "verify:new", "save"), events)
        assertEquals(AutomaticConnectionResult("paired", id), result)
    }
    @Test fun invalidNewIdentityIsNeverSaved() = runBlocking {
        var stored: Stored? = null
        try {
            automaticConnection(origin, { stored }, { it.origin }, { "invalid" },
                { Stored(origin, "new") }, { stored = it })
            fail("Invalid identity must fail")
        } catch (_: IllegalStateException) { assertNull(stored) }
    }
}

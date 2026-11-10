package com.dsgpt.mobile

import java.io.ByteArrayInputStream
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = android.app.Application::class)
class AccountReadsTest {
    private val id = "12345678-1234-1234-1234-123456789abc"
    private fun grant() = JSONObject().put("id", id).put("label", "Private page")
        .put("origin", "https://accounts.example").put("read_path", "/private.txt")
        .put("task_revision", 3).put("profile_revision", 2).put("expires_at", 2000.125)
    private fun page(text: String = "Private text") = JSONObject().put("session_id", id)
        .put("text", text).put("truncated", false)
    private fun rejected(block: () -> Unit) {
        try { block(); fail("Expected rejection") } catch (_: IllegalArgumentException) { }
    }

    @Test fun grantsUseFractionalExpiryAndExactTaskRevision() {
        val data = JSONArray().put(grant()).toString()
        assertEquals(id, accountReadGrants(data, 3, 1999).single().id)
        assertTrue(accountReadGrants(data, 4, 1999).isEmpty())
        assertTrue(accountReadGrants(data, 3, 2001).isEmpty())
        val legacy = JSONArray().put(grant().put("profile_revision", JSONObject.NULL)).toString()
        assertEquals(id, accountReadGrants(legacy, 3, 1999).single().id)
    }

    @Test fun malformedAndDuplicateGrantsDoNotBecomeReadTargets() {
        for ((field, value) in listOf("id" to "../read", "origin" to "https://secret@accounts.example",
            "origin" to "http://accounts.example", "read_path" to "//other.example/page",
            "read_path" to "/page?secret=example", "label" to "bad\nlabel",
            "profile_revision" to 0, "task_revision" to "3", "expires_at" to "2000")) {
            rejected { accountReadGrants(JSONArray().put(grant().put(field, value)).toString(), 3, 1000) }
        }
        rejected { accountReadGrants(JSONArray().put(grant()).put(grant()).toString(), 3, 1000) }
        rejected { accountReadGrants(JSONArray(List(65) { grant() }).toString(), 3, 1000) }
    }

    @Test fun boundedTextIsUnicodeAwareAndNeverCoercesObjectsOrFlags() {
        val unicode = "\uD83D\uDE80".repeat(12000)
        assertEquals(unicode, accountReadPage(page(unicode).toString()).text)
        rejected { accountReadPage(page(unicode + "x").toString()) }
        rejected { accountReadPage(page().put("text", JSONObject().put("secret", "value")).toString()) }
        rejected { accountReadPage(page().put("truncated", "false").toString()) }
    }

    @Test fun streamingBodyCapAlsoAppliesWithoutContentLength() {
        assertEquals(ACCOUNT_RESPONSE_BYTES, boundedAccountBody(ByteArrayInputStream(ByteArray(ACCOUNT_RESPONSE_BYTES) { 65 })).length)
        try {
            boundedAccountBody(ByteArrayInputStream(ByteArray(ACCOUNT_RESPONSE_BYTES + 1) { 65 }))
            fail("Expected overflow rejection")
        } catch (_: IllegalStateException) { }
    }
}

package com.dsgpt.mobile
import org.junit.Assert.*
import org.junit.Test
class AttachmentsTest {
    @Test fun utf8PreservesBomAndRejectsReplacementOrOversize() {
        val text = "\uFEFFCOBALT\r\né"
        assertEquals(text, decodeAttachment("file.txt", text.toByteArray(Charsets.UTF_8)).text)
        assertThrows(IllegalArgumentException::class.java) { decodeAttachment("file.txt", byteArrayOf(0xff.toByte())) }
        assertThrows(IllegalArgumentException::class.java) { decodeAttachment("file.txt", ByteArray(65537)) }
    }
    @Test fun filenameControlsAndByteLimitsAreExplicit() {
        for(name in listOf("../a.txt", "C:a.py", "NUL.txt", "file.exe", "file.pdf", "a.txt ", ".txt")) {
            assertThrows(IllegalArgumentException::class.java) { validateAttachments(listOf(DraftAttachment(name, "text"))) }
        }
        assertThrows(IllegalArgumentException::class.java) { validateAttachments(listOf(DraftAttachment("a.txt", "a\u0000b"))) }
        assertThrows(IllegalArgumentException::class.java) { validateAttachments(listOf(DraftAttachment("a.txt", "é".repeat(32769)))) }
        assertThrows(IllegalArgumentException::class.java) { validateAttachments((0..2).map { DraftAttachment("$it.txt", "a".repeat(65536)) }) }
        validateAttachments(listOf(DraftAttachment("safe.py", "print('reference only')")))
    }
    @Test fun documentsHaveSeparateOriginalAndExtractedTextBounds() {
        validateAttachments(listOf(DraftAttachment("sample.docx", "Extracted", "eA==")))
        assertThrows(IllegalArgumentException::class.java) { validateAttachments(listOf(DraftAttachment("wrong.txt", "Text", "eA=="))) }
        assertThrows(IllegalArgumentException::class.java) { validateAttachments(listOf(DraftAttachment("large.docx", "Text", "A".repeat(699056)))) }
        assertThrows(IllegalArgumentException::class.java) { validateAttachments(listOf(DraftAttachment("long.docx", "x".repeat(65537), "eA=="))) }
    }
}

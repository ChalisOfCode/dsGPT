package com.dsgpt.mobile

import org.junit.Assert.assertEquals
import org.junit.Test

class DictationDraftTest {
    @Test fun hypothesesReplaceOnlyTheCurrentUtteranceAndKeepTypedPrefix() {
        val draft = DictationDraft("My original draft:")
        assertEquals("My original draft: I can", draft.partial("I can"))
        assertEquals("My original draft: I can hear", draft.partial("I can hear"))
        assertEquals("My original draft: I can hear you", draft.finish("I can hear you"))
        assertEquals("My original draft: I can hear you add this", draft.partial("add this"))
        assertEquals("My original draft: I can hear you add this too", draft.finish("add this too"))
    }
    @Test fun EmptyResultsDoNotDuplicateOrEraseCommittedText() {
        val draft = DictationDraft("")
        assertEquals("hello", draft.finish("hello"))
        assertEquals("hello", draft.partial(""))
        assertEquals("hello", draft.finish(""))
    }
}

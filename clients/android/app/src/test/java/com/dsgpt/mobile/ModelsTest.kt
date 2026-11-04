package com.dsgpt.mobile

import org.junit.Assert.*
import org.junit.Test

class ModelsTest {
    @Test fun modelBudgetsAndIdentityRejectInvalidEdits() {
        val valid = ModelForm(id = "local-model", name = "Local", context = "512", output = "128")
        assertTrue(valid.validNumbers()); assertTrue(valid.validIdentity())
        for(value in listOf("", "511", "131073", "1.5", "999999999999")) assertFalse(valid.copy(context = value).validNumbers())
        for(value in listOf("0", "512", "-1", "1.5")) assertFalse(valid.copy(output = value).validNumbers())
        for(value in listOf("-1", "1000", "abc")) assertFalse(valid.copy(gpu = value).validNumbers())
        for(value in listOf("", "../other", "two words", "a/b")) assertFalse(valid.copy(id = value).validIdentity())
        assertFalse(valid.copy(name = "  ").validIdentity())
    }

    @Test fun registrationNeedsCompletedWeightsAndSupportedInstalledRuntime() {
        val form = ModelForm(id = "local", name = "Local", asset = "weights", runtime = "runtime")
        val download = ModelDownload("download", "weights", "downloaded", 100, 100, null)
        val runtime = ModelRuntime("runtime", "windows-x64", true, true, listOf("archive"))
        val ui = ModelsUi(form = form, downloads = listOf(download), runtimes = listOf(runtime))
        assertTrue(ui.canRegister())
        assertFalse(ui.copy(downloads = listOf(download.copy(status = "verifying"))).canRegister())
        assertFalse(ui.copy(runtimes = listOf(runtime.copy(installed = false))).canRegister())
        assertFalse(ui.copy(runtimes = listOf(runtime.copy(supported = false))).canRegister())
        assertFalse(ui.copy(form = form.copy(external = true)).canRegister())
        assertTrue(ui.copy(form = form.copy(external = true, runtimeModel = "local:4b"), downloads = emptyList(), runtimes = emptyList()).canRegister())
    }
}

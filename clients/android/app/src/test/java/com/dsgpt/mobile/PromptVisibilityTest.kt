package com.dsgpt.mobile

import android.app.Application
import android.graphics.Bitmap
import android.graphics.Canvas
import android.view.View
import androidx.compose.foundation.layout.*
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.io.File

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class, qualifiers = "w412dp-h892dp-420dpi")
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class PromptVisibilityTest {
    @get:Rule val compose = createComposeRule()
    private lateinit var view: View

    private fun screen(mode: String, height: Int = 220, fontScale: Float = 1f) {
        val vm = ChatModel(ApplicationProvider.getApplicationContext())
        compose.setContent {
            view = LocalView.current
            val s by vm.state.collectAsState()
            val density = LocalDensity.current
            CompositionLocalProvider(LocalDensity provides Density(density.density, fontScale)) {
                MaterialTheme(colorScheme = darkColorScheme()) {
                    // This is the space remaining below the header with a tall IME open.
                    Surface(Modifier.width(360.dp).height(height.dp).testTag("available-space")) {
                        if (mode == "chat") ChatView(s.copy(model = "local"), vm)
                        else {
                            val work = if (mode == "follow-up") s.work.copy(
                                selected = "finished-task",
                                task = WorkTask("finished-task", "My document", "Write it", "completed", 1,
                                    true, null, "local", 1, "The document is ready."),
                            ) else s.work
                            WorkView(s.copy(model = "local", work = work), vm, {}, { _, _ -> }, {})
                        }
                    }
                }
            }
        }
    }

    private fun verifyVisible(text: String) {
        val editor = compose.onNodeWithTag("prompt-input")
        editor.performClick().performTextInput(text)
        editor.assertTextContains(text).assertIsDisplayed().assertHeightIsAtLeast(56.dp)
        compose.onNodeWithTag("prompt-send").assertIsDisplayed().assertIsEnabled().assertHeightIsEqualTo(48.dp)
        val space = compose.onNodeWithTag("available-space").fetchSemanticsNode().boundsInRoot
        val input = editor.fetchSemanticsNode().boundsInRoot
        val send = compose.onNodeWithTag("prompt-send").fetchSemanticsNode().boundsInRoot
        assertTrue("Editor below the keyboard boundary", input.bottom <= space.bottom + 1)
        assertTrue("Send below the keyboard boundary", send.bottom <= space.bottom + 1)
        assertTrue(input.top >= space.top)
        assertTrue(input.width > 100)
    }

    @Test fun chat_keeps_typed_text_visible_above_tall_keyboard() {
        screen("chat")
        verifyVisible("I can see every word as I type.")
        compose.onNodeWithText("Text, code, documents or images", substring = true).assertDoesNotExist()
        screenshot("chat-typing")
    }

    @Test fun chat_scrolls_long_drafts_with_large_system_text() {
        screen("chat", 220, 1.5f)
        verifyVisible((1..18).joinToString("\n") { "Line $it: my draft stays readable." })
        screenshot("chat-long-draft")
    }

    @Test fun work_keeps_typed_text_visible_in_short_window() {
        screen("work", 180)
        verifyVisible("Create the document using my files.")
        screenshot("work-typing")
    }

    @Test fun work_follow_up_keeps_editor_outside_scrolling_task_details() {
        screen("follow-up", 190, 1.3f)
        verifyVisible("Please improve the second paragraph.")
        screenshot("work-follow-up")
    }

    @Test fun file_help_remains_available_without_using_editor_space() {
        screen("chat")
        verifyVisible("Keep this draft")
        compose.onNodeWithText("＋ Files").performClick()
        compose.onNodeWithText("Text, code, documents or images", substring = true).assertIsDisplayed()
        compose.onNodeWithText("Done").performClick()
        compose.onNodeWithTag("prompt-input").assertTextContains("Keep this draft").assertIsDisplayed()
    }

    private fun screenshot(name: String) {
        val directory = File("build/reports/prompt-visibility").apply { mkdirs() }
        val bounds = compose.onNodeWithTag("available-space").fetchSemanticsNode().boundsInRoot
        // Draw the actual Compose view with Robolectric's native Android canvas.
        // PixelCopy has no physical window surface in this JVM test environment.
        compose.runOnIdle {
            val frame = Bitmap.createBitmap(view.width, view.height, Bitmap.Config.ARGB_8888)
            view.draw(Canvas(frame))
            val crop = Bitmap.createBitmap(frame, bounds.left.toInt(), bounds.top.toInt(),
                bounds.width.toInt(), bounds.height.toInt())
            File(directory, "$name.png").outputStream().use { crop.compress(Bitmap.CompressFormat.PNG, 100, it) }
        }
    }
}

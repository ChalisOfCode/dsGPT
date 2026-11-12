package com.dsgpt.mobile

import android.app.Application
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.*
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class ProjectGroupsViewTest {
    @get:Rule val compose = createComposeRule()
    @Test fun browsesOnlyReturnedGroupsAndClearsOnConnectionChange() {
        val id = "10000000-0000-4000-8000-000000000001"
        var epoch by mutableStateOf(1L)
        val paths = mutableListOf<String>()
        var denied = false
        compose.setContent { MaterialTheme {
            ProjectGroupsView(epoch) { path ->
                paths.add(path)
                if(denied) throw IllegalStateException("controlled denied")
                if(path.contains("offset=")) """[{"id":"$id","name":"Allowed orchard","revision":1}]"""
                else """{"group":{"name":"Allowed orchard"},"members":[{"id":"$id","title":"Original source","kind":"history","source_sha256":"fixture-hash"}]}"""
            }
        } }
        compose.onNodeWithText("Browse project groups").performClick()
        compose.onNodeWithText("Refresh groups").performClick()
        compose.onNodeWithText("Allowed orchard").performClick()
        compose.onNodeWithTag("project-groups-scroll").performScrollToNode(hasText("Original source", substring = true))
        compose.onNodeWithText("Original source · history\nOriginal SHA256: fixture-hash\nSource: $id").assertIsDisplayed()
        assertTrue(paths.all { it.startsWith("/v1/project-groups") })
        compose.runOnIdle { epoch++ }
        compose.onNodeWithText("Original source", substring=true).assertDoesNotExist()
        compose.onNodeWithText("Browse project groups").performClick()
        compose.runOnIdle { denied = true }
        compose.onNodeWithText("Refresh groups").performClick()
        compose.onNodeWithText("Group access changed or is unavailable. Refresh before retrying.").assertExists()
        compose.onNodeWithText("Allowed orchard").assertDoesNotExist()
    }
}

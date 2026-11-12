package com.dsgpt.mobile

import android.app.Application
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.*
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import org.json.JSONObject
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class WorkDocumentEvidenceTest {
    @get:Rule val compose = createComposeRule()

    @Test fun distinguishesPartialReviewErrorsAndHistoricalEvidence() {
        val partial = "Rendered 2 pages. Visual review recorded for pages: 1 (1/2). Review is not a layout pass."
        val errors = "Calculation has errors or changes. Formatting preservation and visual layout are unverified."
        val stale = "Historical document result. Current-source validation is unavailable."
        fun detail(value: String) = JSONObject().put("document_validation_summary", value).toString()
        var current by mutableStateOf(detail(partial))
        compose.setContent { MaterialTheme { WorkDocumentEvidence(current) } }
        compose.onNodeWithText(partial).assertIsDisplayed()
        compose.runOnIdle { current = detail(errors) }
        compose.onNodeWithText(partial).assertDoesNotExist()
        compose.onNodeWithText(errors).assertIsDisplayed()
        compose.runOnIdle { current = detail(stale) }
        compose.onNodeWithText(errors).assertDoesNotExist()
        compose.onNodeWithText(stale).assertIsDisplayed()
        compose.runOnIdle { current = "{}" }
        compose.onNodeWithText(stale).assertDoesNotExist()
    }
}

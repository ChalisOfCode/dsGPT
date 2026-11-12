package com.dsgpt.mobile

import android.app.Application
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.*
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import kotlinx.coroutines.CompletableDeferred
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class AccountReadViewTest {
    @get:Rule val compose = createComposeRule()
    private val grant = AccountReadGrant("12345678-1234-1234-1234-123456789abc",
        "Controlled account", "https://accounts.example", "/private.txt", System.currentTimeMillis() / 1000.0 + 3600)

    @Test fun privateTextRequiresExplicitReadAndIsClearedOnClose() {
        var lists = 0; var reads = 0
        compose.setContent { MaterialTheme { AccountReadView(
            grants = { lists++; listOf(grant) }, read = { reads++; AccountReadPage("Synthetic private page", true) }) } }
        compose.onNodeWithText("Private account pages").performClick()
        compose.runOnIdle { assertEquals(0, lists); assertEquals(0, reads) }
        compose.onNodeWithText("Check private account grants").performClick()
        compose.onNodeWithText("Read approved page").performScrollTo().performClick()
        compose.onNodeWithText("Synthetic private page").performScrollTo().assertIsDisplayed()
        val notice = "Only the beginning of the page is shown."
        compose.onNodeWithTag("private-account-scroll").performScrollToNode(hasText(notice))
        compose.onNodeWithText(notice).assertIsDisplayed()
        compose.onNodeWithText("Close private account view").performClick()
        compose.onNodeWithText("Private account pages").performClick()
        compose.onNodeWithText("Synthetic private page").assertDoesNotExist()
        compose.runOnIdle { assertEquals(1, lists); assertEquals(1, reads) }
    }

    @Test fun lateReadCannotReappearAfterConnectionOrRevisionKeyChanges() {
        val response = CompletableDeferred<AccountReadPage>()
        var epoch by mutableStateOf(1)
        compose.setContent { MaterialTheme { key(epoch) { AccountReadView(
            grants = { listOf(grant) }, read = { response.await() }) } } }
        compose.onNodeWithText("Private account pages").performClick()
        compose.onNodeWithText("Check private account grants").performClick()
        compose.onNodeWithText("Read approved page").performScrollTo().performClick()
        compose.runOnIdle { epoch++; response.complete(AccountReadPage("Stale private result", false)) }
        compose.onNodeWithText("Stale private result").assertDoesNotExist()
        compose.onNodeWithText("Close private account view").assertDoesNotExist()
    }

    @Test fun serverErrorTextIsNotDisplayedOrAutomaticallyRetried() {
        var reads = 0
        compose.setContent { MaterialTheme { AccountReadView(grants = { listOf(grant) },
            read = { reads++; error("PRIVATE_ERROR_SENTINEL") }) } }
        compose.onNodeWithText("Private account pages").performClick()
        compose.onNodeWithText("Check private account grants").performClick()
        compose.onNodeWithText("Read approved page").performScrollTo().performClick()
        compose.onNodeWithText("PRIVATE_ERROR_SENTINEL", substring = true).assertDoesNotExist()
        compose.onNodeWithText("Account access is unavailable.", substring = true).performScrollTo().assertIsDisplayed()
        compose.runOnIdle { assertEquals(1, reads) }
    }
}

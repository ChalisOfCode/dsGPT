package com.dsgpt.mobile

import android.app.Application
import java.net.ServerSocket
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread
import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class AccountReadTransportTest {
    private val id = "12345678-1234-1234-1234-123456789abc"

    private fun serve(reply: String, block: suspend (Api) -> Unit) {
        ServerSocket(0, 1, java.net.InetAddress.getLoopbackAddress()).use { server ->
            server.soTimeout = 3000
            val worker = thread(isDaemon = true) {
                server.accept().use { client ->
                    client.soTimeout = 3000
                    val reader = client.getInputStream().bufferedReader()
                    while (!reader.readLine().isNullOrEmpty()) { }
                    client.getOutputStream().write(reply.toByteArray())
                }
            }
            runBlocking { withTimeout(5000) { block(Api("http://127.0.0.1:${server.localPort}", "synthetic-device-token")) } }
            worker.join(3500)
            assertFalse(worker.isAlive)
        }
    }

    @Test fun readsRequireJsonAndNeverReturnErrorBodyOrRedirect() {
        for (reply in listOf(
            "HTTP/1.1 403 Forbidden\r\nContent-Length: 15\r\n\r\nSECRET_SENTINEL",
            "HTTP/1.1 302 Found\r\nLocation: https://accounts.example/private\r\nContent-Length: 0\r\n\r\n",
            "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 0\r\n\r\n")) {
            serve(reply) { api ->
                try { api.accountReadRequest(id); fail("Expected denial") }
                catch (e: IllegalStateException) { assertEquals("Private account access unavailable", e.message) }
            }
        }
    }

    @Test fun boundedJsonBodyIsDeliveredWithoutGenericRequestHandling() {
        serve("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\n\r\n[]") { api ->
            assertEquals("[]", api.accountReadRequest(id))
        }
        serve("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 262145\r\n\r\n") { api ->
            try { api.accountReadRequest(id); fail("Expected overflow denial") }
            catch (e: IllegalStateException) { assertEquals("Private account access unavailable", e.message) }
        }
    }

    @Test fun cancellationClosesTheOutstandingSocket() = runBlocking {
        val accepted = CountDownLatch(1)
        val ended = CountDownLatch(1)
        ServerSocket(0, 1, java.net.InetAddress.getLoopbackAddress()).use { server ->
            server.soTimeout = 3000
            val worker = thread(isDaemon = true) {
                server.accept().use { client ->
                    client.soTimeout = 3000
                    val reader = client.getInputStream().bufferedReader()
                    while (!reader.readLine().isNullOrEmpty()) { }
                    accepted.countDown()
                    if (reader.read() == -1) ended.countDown()
                }
            }
            val api = Api("http://127.0.0.1:${server.localPort}", "synthetic-device-token")
            val job = launch(Dispatchers.IO) { api.accountReadRequest(id) }
            assertTrue(accepted.await(3, TimeUnit.SECONDS))
            job.cancelAndJoin()
            assertTrue(ended.await(3, TimeUnit.SECONDS))
            worker.join(3500)
        }
    }
}

package co.eko.sahayak.recsync

import android.content.Context
import junit.framework.TestCase.assertEquals
import junit.framework.TestCase.assertFalse
import junit.framework.TestCase.assertTrue
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner


@RunWith(RobolectricTestRunner::class)
class AutoGMapTest {
    private lateinit var server: MockWebServer
    private lateinit var autoGMap: AutoGMap

    @Before
    fun setup() {
        server = MockWebServer()
        server.start()
    }

    @After
    fun teardown() {
        server.shutdown()
    }

    @Test
    fun parseCurrentApiFormat() {
        // Current format from app/autogmap.py
        val response = """{
            "as_of": "2026-11-11T10:30:00Z",
            "count": 2,
            "numbers": [
                {
                    "phone": "9876543210",
                    "local": "delhi",
                    "name": "Team Member 1",
                    "since": "2026-11-01"
                },
                {
                    "phone": "9876543211",
                    "local": "bangalore",
                    "name": "Team Member 2",
                    "since": "2026-11-02"
                }
            ]
        }"""

        server.enqueue(MockResponse().setBody(response))
        autoGMap = AutoGMap( "test-key", server.url("/numbers").toString())

        val result = autoGMap.syncNumbers()

        assertEquals(true, result.success)
        assertEquals(2, result.totalFetched)
        assertEquals(0, result.testNumbers)  // No test field in current API
        assertEquals(2, result.productionNumbers)
        assertEquals(null, result.error)
    }

    @Test
    fun parseApiFormatWithTestField() {
        // Future format when Mansi adds test field
        val response = """{
            "as_of": "2026-11-11T10:30:00Z",
            "count": 3,
            "numbers": [
                {
                    "phone": "9876543210",
                    "local": "test",
                    "name": "Test Team 1",
                    "since": "2026-11-01",
                    "test": true
                },
                {
                    "phone": "9876543211",
                    "local": "test",
                    "name": "Test Team 2",
                    "since": "2026-11-02",
                    "test": true
                },
                {
                    "phone": "9876543212",
                    "local": "bangalore",
                    "name": "Prod RM",
                    "since": "2026-11-01",
                    "test": false
                }
            ]
        }"""

        server.enqueue(MockResponse().setBody(response))
        autoGMap = AutoGMap( "test-key", server.url("/numbers").toString())

        val result = autoGMap.syncNumbers()

        assertEquals(true, result.success)
        assertEquals(3, result.totalFetched)
        assertEquals(2, result.testNumbers)
        assertEquals(1, result.productionNumbers)
    }

    @Test
    fun cacheNumbersAfterSync() {
        val response = """{
            "count": 1,
            "numbers": [
                {"phone": "9876543210", "local": "delhi", "name": "RM Test", "since": "2026-11-01"}
            ]
        }"""

        server.enqueue(MockResponse().setBody(response))
        autoGMap = AutoGMap( "test-key", server.url("/numbers").toString())

        autoGMap.syncNumbers()

        assertTrue("Number should be valid", autoGMap.isValidNumber("9876543210"))
        assertFalse("Invalid number should not exist", autoGMap.isValidNumber("0000000000"))
    }

    @Test
    fun identifyTestNumbers() {
        val response = """{
            "count": 2,
            "numbers": [
                {"phone": "9999999999", "name": "Test", "test": true},
                {"phone": "8888888888", "name": "Prod", "test": false}
            ]
        }"""

        server.enqueue(MockResponse().setBody(response))
        autoGMap = AutoGMap( "test-key", server.url("/numbers").toString())

        autoGMap.syncNumbers()

        assertTrue("Test number should be marked as test", autoGMap.isTestNumber("9999999999"))
        assertFalse("Prod number should not be marked as test", autoGMap.isTestNumber("8888888888"))
    }

    @Test
    fun filterProductionNumbers() {
        val response = """{
            "count": 3,
            "numbers": [
                {"phone": "1111111111", "test": true},
                {"phone": "2222222222", "test": false},
                {"phone": "3333333333", "test": false}
            ]
        }"""

        server.enqueue(MockResponse().setBody(response))
        autoGMap = AutoGMap( "test-key", server.url("/numbers").toString())

        autoGMap.syncNumbers()

        val prodNumbers = autoGMap.getProductionNumbers()
        assertEquals(2, prodNumbers.size)
        assertEquals("2222222222", prodNumbers[0].number)
        assertEquals("3333333333", prodNumbers[1].number)
    }

    @Test
    fun filterTestNumbers() {
        val response = """{
            "count": 3,
            "numbers": [
                {"phone": "1111111111", "test": true},
                {"phone": "2222222222", "test": true},
                {"phone": "3333333333", "test": false}
            ]
        }"""

        server.enqueue(MockResponse().setBody(response))
        autoGMap = AutoGMap( "test-key", server.url("/numbers").toString())

        autoGMap.syncNumbers()

        val testNumbers = autoGMap.getTestNumbers()
        assertEquals(2, testNumbers.size)
        assertEquals("1111111111", testNumbers[0].number)
        assertEquals("2222222222", testNumbers[1].number)
    }

    @Test
    fun handleNetworkError() {
        server.enqueue(MockResponse().setResponseCode(500))
        autoGMap = AutoGMap( "test-key", server.url("/numbers").toString())

        val result = autoGMap.syncNumbers()

        assertEquals(false, result.success)
        assertEquals(0, result.totalFetched)
        assertTrue("Error should mention HTTP 500", result.error?.contains("500") ?: false)
    }

    @Test
    fun handleAuthenticationError() {
        server.enqueue(MockResponse().setResponseCode(401))
        autoGMap = AutoGMap( "bad-key", server.url("/numbers").toString())

        val result = autoGMap.syncNumbers()

        assertEquals(false, result.success)
        assertEquals(0, result.totalFetched)
        assertTrue("Error should mention 401", result.error?.contains("401") ?: false)
    }

    @Test
    fun handleEmptyResponse() {
        val response = """{"count": 0, "numbers": []}"""

        server.enqueue(MockResponse().setBody(response))
        autoGMap = AutoGMap( "test-key", server.url("/numbers").toString())

        val result = autoGMap.syncNumbers()

        assertEquals(true, result.success)
        assertEquals(0, result.totalFetched)
        assertEquals(0, result.testNumbers)
        assertEquals(0, result.productionNumbers)
    }

    @Test
    fun clearCacheResets() {
        val response = """{
            "count": 1,
            "numbers": [{"phone": "9876543210", "test": false}]
        }"""

        server.enqueue(MockResponse().setBody(response))
        autoGMap = AutoGMap( "test-key", server.url("/numbers").toString())

        autoGMap.syncNumbers()
        assertTrue("Number should exist after sync", autoGMap.isValidNumber("9876543210"))

        autoGMap.clearCache()
        assertFalse("Cache should be empty after clear", autoGMap.isValidNumber("9876543210"))
    }
}

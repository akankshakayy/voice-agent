package co.eko.sahayak.recsync

import android.content.Context
import junit.framework.TestCase.assertEquals
import junit.framework.TestCase.assertFalse
import junit.framework.TestCase.assertTrue
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Before
import org.junit.Test


class RecordingUploaderTest {
    private lateinit var server: MockWebServer
    private lateinit var api: Api
    private lateinit var autoGMap: AutoGMap
    private lateinit var uploader: RecordingUploader

    private val testFile = RecFile("uri", "test.m4a", 1024, System.currentTimeMillis())
    private val testCall = CallEntry(
        startMs = System.currentTimeMillis(),
        durationSec = 120,
        number = "9876543210",
        accountId = "2",
        direction = "incoming"
    )

    @Before
    fun setup() {
        server = MockWebServer()
        server.start()

        api = Api(server.url("").toString(), "test-token")
        autoGMap = AutoGMap( "test-key", server.url("/numbers").toString())
        uploader = RecordingUploader(api, autoGMap)
    }

    @After
    fun teardown() {
        server.shutdown()
    }

    @Test
    fun validateRmRecordingWithValidNumber() {
        val response = """{
            "count": 1,
            "numbers": [{"phone": "9876543210", "local": "delhi", "name": "RM Test"}]
        }"""
        server.enqueue(MockResponse().setBody(response))
        autoGMap.syncNumbers()

        val request = RecordingUploader.UploadRequest(
            file = testFile,
            call = testCall,
            deviceId = "device1",
            rmId = 101,
            mode = "rm"
        )

        val result = uploader.validateRecording(request)

        assertTrue("Validation should pass for valid number", result is RecordingUploader.ValidationResult.Valid)
        assertEquals(false, (result as RecordingUploader.ValidationResult.Valid).isTest)
    }

    @Test
    fun rejectRmRecordingWithInvalidNumber() {
        val response = """{"count": 0, "numbers": []}"""
        server.enqueue(MockResponse().setBody(response))
        autoGMap.syncNumbers()

        val request = RecordingUploader.UploadRequest(
            file = testFile,
            call = testCall.copy(number = "0000000000"),  // Number not in AutoGMap
            deviceId = "device1",
            rmId = 101,
            mode = "rm"
        )

        val result = uploader.validateRecording(request)

        assertTrue("Validation should fail for invalid number", result is RecordingUploader.ValidationResult.Invalid)
        assertTrue("Error should mention number validation",
            (result as RecordingUploader.ValidationResult.Invalid).reason.contains("not in AutoGMap"))
    }

    @Test
    fun identifyTestNumberInValidation() {
        val response = """{
            "count": 1,
            "numbers": [{"phone": "9876543210", "test": true, "name": "Test RM"}]
        }"""
        server.enqueue(MockResponse().setBody(response))
        autoGMap.syncNumbers()

        val request = RecordingUploader.UploadRequest(
            file = testFile,
            call = testCall,
            deviceId = "device1",
            rmId = 101,
            mode = "rm"
        )

        val result = uploader.validateRecording(request)

        assertTrue("Validation should pass", result is RecordingUploader.ValidationResult.Valid)
        assertEquals(true, (result as RecordingUploader.ValidationResult.Valid).isTest)
    }

    @Test
    fun skipAutoGMapValidationForDcMode() {
        // DC mode should not validate against AutoGMap
        val request = RecordingUploader.UploadRequest(
            file = testFile,
            call = testCall,
            deviceId = "device1",
            rmId = -1,
            dcId = 201,
            mode = "dc"
        )

        val result = uploader.validateRecording(request)

        assertTrue("Validation should pass for DC mode", result is RecordingUploader.ValidationResult.Valid)
        assertEquals(false, (result as RecordingUploader.ValidationResult.Valid).isTest)
    }

    @Test
    fun skipAutoGMapValidationForEmployeeMode() {
        // Employee mode should not validate against AutoGMap
        val request = RecordingUploader.UploadRequest(
            file = testFile,
            call = testCall,
            deviceId = "device1",
            rmId = -1,
            employeeId = 301,
            mode = "employee"
        )

        val result = uploader.validateRecording(request)

        assertTrue("Validation should pass for Employee mode", result is RecordingUploader.ValidationResult.Valid)
        assertEquals(false, (result as RecordingUploader.ValidationResult.Valid).isTest)
    }

    @Test
    fun rejectRecordingWithNoPhoneNumber() {
        val response = """{
            "count": 1,
            "numbers": [{"phone": "9876543210", "local": "delhi"}]
        }"""
        server.enqueue(MockResponse().setBody(response))
        autoGMap.syncNumbers()

        val request = RecordingUploader.UploadRequest(
            file = testFile,
            call = testCall.copy(number = ""),  // Empty phone number
            deviceId = "device1",
            rmId = 101,
            mode = "rm"
        )

        val result = uploader.validateRecording(request)

        assertTrue("Validation should fail for empty number", result is RecordingUploader.ValidationResult.Invalid)
    }

    @Test
    fun workWithoutAutoGMap() {
        // Should work gracefully when AutoGMap is null
        val uploaderWithoutAutoGMap = RecordingUploader(api, null)

        val request = RecordingUploader.UploadRequest(
            file = testFile,
            call = testCall,
            deviceId = "device1",
            rmId = 101,
            mode = "rm"
        )

        val result = uploaderWithoutAutoGMap.validateRecording(request)

        assertTrue("Validation should pass when AutoGMap is disabled",
            result is RecordingUploader.ValidationResult.Valid)
    }

    @Test
    fun getSyncStatus() {
        val response = """{
            "count": 3,
            "numbers": [
                {"phone": "1111111111", "test": true},
                {"phone": "2222222222", "test": false},
                {"phone": "3333333333", "test": false}
            ]
        }"""
        server.enqueue(MockResponse().setBody(response))
        autoGMap.syncNumbers()

        val status = uploader.getSyncStatus()

        assertTrue("Status should include sync time", status?.containsKey("lastSyncTime") ?: false)
        assertEquals(3, status?.get("totalCached"))
        assertEquals(1, status?.get("testCount"))
        assertEquals(2, status?.get("productionCount"))
    }

    @Test
    fun getNumberStats() {
        val response = """{
            "count": 2,
            "numbers": [
                {"phone": "1111111111", "test": true},
                {"phone": "2222222222", "test": false}
            ]
        }"""
        server.enqueue(MockResponse().setBody(response))
        autoGMap.syncNumbers()

        val stats = uploader.getNumberStats()

        assertEquals(true, stats["hasAutoGMap"])
        assertEquals(2, stats["totalNumbers"])
        assertEquals(1, stats["testNumbers"])
        assertEquals(1, stats["productionNumbers"])
    }

    @Test
    fun getNumberStatsWithoutAutoGMap() {
        val uploaderWithoutAutoGMap = RecordingUploader(api, null)

        val stats = uploaderWithoutAutoGMap.getNumberStats()

        assertEquals(false, stats["hasAutoGMap"])
    }
}

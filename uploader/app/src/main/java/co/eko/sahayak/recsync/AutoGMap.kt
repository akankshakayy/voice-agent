package co.eko.sahayak.recsync

import android.content.Context
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * AutoGMap integration for fetching valid RM phone numbers.
 * Supports test numbers (marked with "test": true) for development/staging.
 */
class AutoGMap(private val context: Context, private val apiKey: String, private val apiUrl: String) {

    data class PhoneNumber(
        val number: String,
        val isTest: Boolean = false,
        val name: String? = null,
        val rmId: Int? = null
    )

    data class SyncResult(
        val success: Boolean,
        val totalFetched: Int,
        val testNumbers: Int,
        val productionNumbers: Int,
        val error: String? = null,
        val lastSyncAt: Long = System.currentTimeMillis()
    )

    private val client = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .build()

    private val cache = mutableMapOf<String, PhoneNumber>()
    private var lastSyncTime: Long = 0L

    /**
     * Fetch numbers from AutoGMap API.
     * Current format from backend (as of Nov 11, 2026):
     * {
     *   "as_of": "2026-11-11T10:30:00Z",
     *   "count": N,
     *   "numbers": [
     *     {"phone": "9876543210", "local": "...", "name": "...", "since": "2026-11-01"}
     *   ]
     * }
     *
     * Future format (when Mansi adds test support):
     *   Add "test": true to distinguish team test numbers
     */
    fun syncNumbers(): SyncResult = try {
        val req = Request.Builder()
            .url(apiUrl)
            .header("X-API-Key", apiKey)  // AutoGMap uses X-API-Key header
            .header("User-Agent", "Sahayak-Uploader/1.0")
            .get()
            .build()

        client.newCall(req).execute().use { response ->
            if (!response.isSuccessful) {
                return SyncResult(
                    success = false,
                    totalFetched = 0,
                    testNumbers = 0,
                    productionNumbers = 0,
                    error = "HTTP ${response.code}: ${response.message}"
                )
            }

            val body = response.body?.string().orEmpty()
            val json = JSONObject(body)
            val numbersArray = json.optJSONArray("numbers") ?: JSONArray()

            var testCount = 0
            var prodCount = 0
            cache.clear()

            for (i in 0 until numbersArray.length()) {
                val numberObj = numbersArray.getJSONObject(i)
                // Current backend field: "phone" (not "number")
                val phone = numberObj.getString("phone")
                // Future field: "test" (will be added by Mansi)
                val isTest = numberObj.optBoolean("test", false)
                val name = numberObj.optString("name", null)
                val localInfo = numberObj.optString("local", null)
                val since = numberObj.optString("since", null)

                val phoneNum = PhoneNumber(
                    number = phone,
                    isTest = isTest,
                    name = name,
                    rmId = null  // AutoGMap API doesn't include rm_id yet
                )

                cache[phone] = phoneNum

                if (isTest) testCount++ else prodCount++
            }

            lastSyncTime = System.currentTimeMillis()

            SyncResult(
                success = true,
                totalFetched = cache.size,
                testNumbers = testCount,
                productionNumbers = prodCount,
                error = null,
                lastSyncAt = lastSyncTime
            )
        }
    } catch (e: IOException) {
        SyncResult(
            success = false,
            totalFetched = 0,
            testNumbers = 0,
            productionNumbers = 0,
            error = e.message ?: e.javaClass.simpleName
        )
    }

    /**
     * Check if a number is valid (exists in our cached list).
     */
    fun isValidNumber(number: String): Boolean = cache.containsKey(number)

    /**
     * Check if a number is a test number.
     */
    fun isTestNumber(number: String): Boolean = cache[number]?.isTest == true

    /**
     * Get details for a number.
     */
    fun getNumber(number: String): PhoneNumber? = cache[number]

    /**
     * Get all valid numbers (production only).
     */
    fun getProductionNumbers(): List<PhoneNumber> = cache.values.filter { !it.isTest }

    /**
     * Get all test numbers.
     */
    fun getTestNumbers(): List<PhoneNumber> = cache.values.filter { it.isTest }

    /**
     * Get all cached numbers.
     */
    fun getAllNumbers(): List<PhoneNumber> = cache.values.toList()

    /**
     * Get sync status.
     */
    fun getSyncStatus(): Map<String, Any> = mapOf(
        "lastSyncTime" to lastSyncTime,
        "totalCached" to cache.size,
        "testCount" to cache.values.count { it.isTest },
        "productionCount" to cache.values.count { !it.isTest }
    )

    /**
     * Clear local cache (useful for testing or manual refresh).
     */
    fun clearCache() {
        cache.clear()
        lastSyncTime = 0L
    }
}

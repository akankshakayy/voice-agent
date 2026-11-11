package co.eko.sahayak.recsync

import android.content.ContentResolver
import java.io.IOException

/**
 * Orchestrates recording upload with AutoGMap number validation and test/production handling.
 */
class RecordingUploader(
    private val api: Api,
    private val autoGMap: AutoGMap?
) {

    sealed class ValidationResult {
        data class Valid(val isTest: Boolean, val number: AutoGMap.PhoneNumber? = null) : ValidationResult()
        data class Invalid(val reason: String) : ValidationResult()
        data class SkipTest(val reason: String) : ValidationResult()
    }

    data class UploadRequest(
        val file: RecFile,
        val call: CallEntry,
        val deviceId: String,
        val rmId: Int,
        val mode: String = "rm",
        val dcId: Int = -1,
        val employeeId: Int = -1,
        val consentToken: String = ""
    )

    /**
     * Validate a recording before upload.
     * For RM mode with AutoGMap: checks if the number is valid.
     * For test numbers: marks them as test so they can be handled appropriately.
     */
    fun validateRecording(request: UploadRequest): ValidationResult {
        // AutoGMap validation only applies to RM mode
        if (request.mode != "rm" || autoGMap == null) {
            return ValidationResult.Valid(isTest = false)
        }

        val otherNumber = request.call.number
        if (otherNumber.isEmpty()) {
            return ValidationResult.Invalid("No phone number in call metadata")
        }

        // Check if the number is in our valid list
        if (!autoGMap.isValidNumber(otherNumber)) {
            return ValidationResult.Invalid("Number $otherNumber not in AutoGMap valid numbers list")
        }

        // Check if it's a test number
        val isTest = autoGMap.isTestNumber(otherNumber)
        val numberInfo = autoGMap.getNumber(otherNumber)

        return ValidationResult.Valid(isTest = isTest, number = numberInfo)
    }

    /**
     * Upload a recording with validation and error handling.
     */
    fun upload(
        resolver: ContentResolver,
        request: UploadRequest
    ): Pair<Api.Upload, ValidationResult?> {
        // Validate first
        val validation = validateRecording(request)
        if (validation is ValidationResult.Invalid) {
            // Invalid recordings are not uploaded (will be skipped)
            return Pair(
                Api.Upload.Rejected(400, validation.reason),
                validation
            )
        }

        // Proceed with upload (same for test and production)
        val uploadResult = api.upload(
            resolver = resolver,
            file = request.file,
            call = request.call,
            deviceId = request.deviceId,
            rmId = request.rmId,
            mode = request.mode,
            dcId = request.dcId,
            employeeId = request.employeeId,
            consentToken = request.consentToken
        )

        return Pair(uploadResult, validation)
    }

    /**
     * Sync AutoGMap numbers (if available).
     * Should be called periodically (e.g., every 15 minutes).
     */
    fun syncNumbers(): AutoGMap.SyncResult? {
        return autoGMap?.syncNumbers()
    }

    /**
     * Get current sync status.
     */
    fun getSyncStatus(): Map<String, Any>? {
        return autoGMap?.getSyncStatus()
    }

    /**
     * Get statistics about known numbers.
     */
    fun getNumberStats(): Map<String, Any> {
        return if (autoGMap != null) {
            mapOf(
                "hasAutoGMap" to true,
                "totalNumbers" to autoGMap.getAllNumbers().size,
                "testNumbers" to autoGMap.getTestNumbers().size,
                "productionNumbers" to autoGMap.getProductionNumbers().size
            )
        } else {
            mapOf("hasAutoGMap" to false)
        }
    }
}

package co.eko.sahayak.recsync

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.net.Uri
import android.provider.CallLog
import android.util.Log
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.Worker
import androidx.work.WorkerParameters
import java.time.Duration
import java.time.LocalDate
import java.time.LocalTime
import java.time.ZoneId
import java.time.ZonedDateTime
import java.util.concurrent.TimeUnit

/**
 * One upload run: list new recordings, keep the ones that line up with an answered call on the Eko SIM,
 * upload them, and skip everything else (calls on the personal SIM are never sent).
 */
class UploadWorker(context: Context, params: WorkerParameters) : Worker(context, params) {

    override fun doWork(): Result {
        val s = Settings(applicationContext)
        var uploaded = 0; var duplicates = 0; var skipped = 0; var failed = 0
        var error: String? = null
        fun finish(result: Result): Result {
            s.saveStatus(RunStatus(System.currentTimeMillis(), uploaded, duplicates, skipped, failed, error))
            return result
        }

        if (!s.isConfigured) { error = "Setup isn't finished"; return finish(Result.failure()) }
        for (p in listOf(Manifest.permission.READ_CALL_LOG, Manifest.permission.READ_PHONE_STATE)) {
            if (applicationContext.checkSelfPermission(p) != PackageManager.PERMISSION_GRANTED) {
                error = "Permission missing: ${p.substringAfterLast('.')}"; return finish(Result.failure())
            }
        }

        val now = System.currentTimeMillis()
        val since = s.watermarkMs - Settings.OVERLAP_MS
        val files = try {
            Device.recordings(applicationContext, Uri.parse(s.folderUri), since)
        } catch (e: Exception) {
            error = "Can't read the recordings folder (pick it again): ${e.message}"; return finish(Result.failure())
        }
        val calls = Device.calls(applicationContext, since - Settings.DAY_MS)
        val api = Api(s.serverUrl, s.token)

        // Initialize AutoGMap for RM number validation (optional, gracefully degrades if disabled)
        val autoGMapApiKey = System.getenv("AUTOGMAP_API_KEY") ?: ""
        val autoGMapUrl = System.getenv("AUTOGMAP_NUMBERS_URL") ?: ""
        val autoGMap = if (autoGMapApiKey.isNotEmpty() && autoGMapUrl.isNotEmpty()) {
            try {
                AutoGMap(autoGMapApiKey, autoGMapUrl).apply {
                    val syncResult = syncNumbers()
                    if (syncResult.success) {
                        Log.i(TAG, "AutoGMap sync: ${syncResult.totalFetched} numbers (${syncResult.testNumbers} test)")
                    } else {
                        Log.w(TAG, "AutoGMap sync failed: ${syncResult.error}")
                    }
                }
            } catch (e: Exception) {
                Log.w(TAG, "AutoGMap init failed: ${e.message}")
                null
            }
        } else {
            Log.d(TAG, "AutoGMap disabled (no API key configured)")
            null
        }
        val uploader = RecordingUploader(api, autoGMap)

        // The watermark only moves past an unbroken run of handled files, so a failure is retried next time
        var watermark = s.watermarkMs
        var blocked = false
        var retry = false
        var testUploaded = 0
        for (f in files) {
            if (s.isHandled(f)) { if (!blocked) watermark = maxOf(watermark, f.mtimeMs); continue }
            val age = now - f.mtimeMs
            if (age < STILL_WRITING_MS) { blocked = true; continue }

            val call = Matcher.match(f, calls)
            val outcome: String = when {
                f.size > Api.MAX_BYTES -> "skip: over 100 MB"
                call == null && age < CALL_LOG_LAG_MS -> { blocked = true; continue }   // call log may lag
                call == null -> "skip: no matching call"
                !Matcher.isEkoSim(call.accountId, s.ekoAccountIds) -> "skip: not the Eko SIM"
                s.mode == "dc" && !s.allowedNumbers.contains(call.number) -> "skip: number not in DC allowed list"
                // AutoGMap validation for RM mode (if enabled)
                s.mode == "rm" && autoGMap != null && !autoGMap.isValidNumber(call.number) ->
                    "skip: RM number ${call.number} not in AutoGMap"
                else -> {
                    // Build upload request
                    val uploadRequest = RecordingUploader.UploadRequest(
                        file = f,
                        call = call,
                        deviceId = s.deviceId,
                        rmId = s.rmId,
                        mode = s.mode,
                        dcId = s.dcId,
                        employeeId = s.employeeId,
                        consentToken = s.consentToken
                    )

                    // Upload with validation
                    val (uploadResult, validation) = uploader.upload(applicationContext.contentResolver, uploadRequest)

                    // Track test numbers
                    if (validation is RecordingUploader.ValidationResult.Valid && validation.isTest) {
                        testUploaded++
                        Log.d(TAG, "Test number uploaded: ${call.number} (${validation.number?.name})")
                    }

                    when (uploadResult) {
                        is Api.Upload.Ok -> if (uploadResult.duplicate) "duplicate" else "uploaded"
                        is Api.Upload.Rejected -> "rejected ${uploadResult.code}: ${uploadResult.detail}"
                        is Api.Upload.Unauthorized -> {
                            error = "Token rejected: ${uploadResult.detail}. Ask the Sahayak admin for a new token."
                            return finish(Result.failure())
                        }
                        is Api.Upload.Retry -> { error = uploadResult.detail; retry = true; break }
                    }
                }
            }
            Log.i(TAG, "${f.name}: $outcome")
            when {
                outcome == "uploaded" -> uploaded++
                outcome == "duplicate" -> duplicates++
                outcome.startsWith("skip") -> skipped++
                else -> { failed++; error = "${f.name}: $outcome" }
            }
            s.markHandled(f)
            if (!blocked) watermark = maxOf(watermark, f.mtimeMs)
        }
        if (retry) failed++
        s.watermarkMs = watermark
        s.pruneHandled()

        // Log AutoGMap statistics
        if (autoGMap != null) {
            val status = uploader.getSyncStatus()
            Log.i(TAG, "AutoGMap status: ${status?.get("totalCached")} numbers cached, " +
                "${status?.get("testCount")} test, ${status?.get("productionCount")} production")
        }
        if (testUploaded > 0) {
            Log.i(TAG, "Test uploads this run: $testUploaded")
        }

        // blocked = a recording still being written, or its call not in the call log yet: look again shortly
        return finish(if (retry || blocked) Result.retry() else Result.success())
    }

    companion object {
        const val TAG = "RecSync"
        private const val DAILY = "daily-upload"
        private const val NOW = "upload-now"
        private const val WATCH = "watch-calls"
        private const val AFTER_CALL = "after-call-upload"
        /** Wait this long after a call ends: the dialer needs a moment to finish saving the recording. */
        private const val AFTER_CALL_DELAY_MIN = 3L
        private const val STILL_WRITING_MS = 2 * 60 * 1000L
        private const val CALL_LOG_LAG_MS = 15 * 60 * 1000L
        private val RUN_AT: LocalTime = LocalTime.of(20, 0)

        private fun constraints(s: Settings) = Constraints.Builder()
            .setRequiredNetworkType(if (s.wifiOnly) NetworkType.UNMETERED else NetworkType.CONNECTED)
            .setRequiresBatteryNotLow(true)
            .build()

        /** Once a day, starting at the next 8 pm (after the RM's working day). */
        fun scheduleDaily(context: Context) {
            val s = Settings(context)
            val req = PeriodicWorkRequestBuilder<UploadWorker>(24, TimeUnit.HOURS)
                .setInitialDelay(delayUntilNext(RUN_AT, ZonedDateTime.now()).toMillis(), TimeUnit.MILLISECONDS)
                .setConstraints(constraints(s))
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 15, TimeUnit.MINUTES)
                .build()
            WorkManager.getInstance(context).enqueueUniquePeriodicWork(DAILY, ExistingPeriodicWorkPolicy.UPDATE, req)
        }

        /**
         * Upload a few minutes after every call. Android wakes [CallWatchWorker] when the call log changes
         * (a call ended), and it queues one upload. Calls close together share one upload; the daily run
         * stays as a safety net. Call this after setup and from [CallWatchWorker] to keep watching.
         */
        fun watchCalls(context: Context) {
            val req = OneTimeWorkRequestBuilder<CallWatchWorker>()
                .setConstraints(Constraints.Builder().addContentUriTrigger(CallLog.Calls.CONTENT_URI, true).build())
                .build()
            WorkManager.getInstance(context).enqueueUniqueWork(WATCH, ExistingWorkPolicy.REPLACE, req)
        }

        fun uploadAfterCall(context: Context) {
            val req = OneTimeWorkRequestBuilder<UploadWorker>()
                .setInitialDelay(AFTER_CALL_DELAY_MIN, TimeUnit.MINUTES)
                .setConstraints(constraints(Settings(context)))
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 2, TimeUnit.MINUTES)
                .build()
            WorkManager.getInstance(context).enqueueUniqueWork(AFTER_CALL, ExistingWorkPolicy.REPLACE, req)
        }

        fun runNow(context: Context) {
            val req = OneTimeWorkRequestBuilder<UploadWorker>()
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 1, TimeUnit.MINUTES)
                .build()
            WorkManager.getInstance(context).enqueueUniqueWork(NOW, ExistingWorkPolicy.REPLACE, req)
        }

        fun delayUntilNext(at: LocalTime, now: ZonedDateTime, zone: ZoneId = now.zone): Duration {
            var next = ZonedDateTime.of(LocalDate.from(now), at, zone)
            if (!next.isAfter(now)) next = next.plusDays(1)
            return Duration.between(now, next)
        }
    }
}


/** Woken by Android when the call log changes, i.e. a call just ended. Queues an upload and keeps watching. */
class CallWatchWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result {
        if (Settings(applicationContext).isConfigured) UploadWorker.uploadAfterCall(applicationContext)
        UploadWorker.watchCalls(applicationContext)
        return Result.success()
    }
}

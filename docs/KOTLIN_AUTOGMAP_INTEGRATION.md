# Kotlin AutoGMap Integration Guide

Guide for integrating AutoGMap number validation into the Sahayak Uploader app.

## Overview

The AutoGMap integration adds:
- ✅ Real-time number validation for RM recordings
- ✅ Test number support (marked with `"test": true`)
- ✅ Local caching of valid numbers
- ✅ Production vs. test number differentiation
- ✅ Automatic sync capability

## Architecture

### Three New Classes

**1. AutoGMap.kt** — Core API client
- Fetches numbers from AutoGMap API
- Caches valid numbers locally
- Distinguishes test vs. production numbers
- Provides query methods (isValid, isTest, getNumber, etc.)

**2. RecordingUploader.kt** — Orchestration layer
- Validates recordings against AutoGMap data
- Handles RM/DC/Employee mode logic
- Returns detailed validation results
- Supports periodic sync

**3. Integration** — In your MainActivity/UploadWorker
- Initialize AutoGMap on startup
- Sync numbers every 15 minutes
- Validate recordings before upload
- Handle test numbers appropriately

## Expected API Format

Assuming Mansi confirms this structure:

```json
{
  "numbers": [
    {
      "number": "9876543210",
      "test": true,
      "name": "Test RM 1",
      "rm_id": 101
    },
    {
      "number": "9876543211",
      "test": false,
      "name": "Prod RM",
      "rm_id": 102
    }
  ]
}
```

**Fields:**
- `number` (string, required): 10-digit phone number
- `test` (boolean, optional): true if this is a test number
- `name` (string, optional): RM or team member name
- `rm_id` (integer, optional): Reference to RM in system

## Integration Steps

### Step 1: Initialize AutoGMap

In your MainActivity or startup code:

```kotlin
class MainActivity : AppCompatActivity() {
    private lateinit var autoGMap: AutoGMap
    private lateinit var uploader: RecordingUploader
    private val s by lazy { Settings(this) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        
        // Initialize AutoGMap with API credentials
        autoGMap = AutoGMap(
            context = this,
            apiKey = s.autoGMapApiKey,  // From Settings or env
            apiUrl = "https://indev.eko.in/autogmap/api/v1/call-recorder/numbers"
        )
        
        // Initialize uploader with AutoGMap validation
        uploader = RecordingUploader(
            api = Api(s.serverUrl, s.token),
            autoGMap = autoGMap
        )
        
        // Sync numbers on startup
        syncNumbers()
    }

    private fun syncNumbers() {
        Thread {
            val result = autoGMap.syncNumbers()
            Log.i("AutoGMap", "Sync: ${result.totalFetched} numbers " +
                "(${result.testNumbers} test, ${result.productionNumbers} prod)")
            
            if (!result.success) {
                Log.e("AutoGMap", "Sync failed: ${result.error}")
            }
        }.start()
    }
}
```

### Step 2: Periodic Sync

Schedule sync every 15 minutes:

```kotlin
companion object {
    fun scheduleAutoGMapSync(context: Context) {
        val req = PeriodicWorkRequestBuilder<AutoGMapSyncWorker>(
            15, TimeUnit.MINUTES
        ).build()
        
        WorkManager.getInstance(context).enqueueUniquePeriodicWork(
            "autogmap-sync",
            ExistingPeriodicWorkPolicy.KEEP,
            req
        )
    }
}

class AutoGMapSyncWorker(context: Context, params: WorkerParameters) : 
    Worker(context, params) {
    
    override fun doWork(): Result = try {
        val autoGMap = AutoGMap(
            context = applicationContext,
            apiKey = Settings(applicationContext).autoGMapApiKey,
            apiUrl = "https://indev.eko.in/autogmap/api/v1/call-recorder/numbers"
        )
        
        val result = autoGMap.syncNumbers()
        if (result.success) {
            Log.i("AutoGMapSync", "Synced ${result.totalFetched} numbers")
            Result.success()
        } else {
            Log.e("AutoGMapSync", "Sync failed: ${result.error}")
            Result.retry()  // Will retry after backoff
        }
    } catch (e: Exception) {
        Log.e("AutoGMapSync", "Sync error", e)
        Result.retry()
    }
}
```

### Step 3: Validate Before Upload

In your upload logic (UploadWorker or custom code):

```kotlin
val request = RecordingUploader.UploadRequest(
    file = recordingFile,
    call = callEntry,
    deviceId = deviceId,
    rmId = rmId,
    mode = "rm",  // or "dc", "employee"
    dcId = -1,
    employeeId = -1,
    consentToken = ""
)

val (uploadResult, validation) = uploader.upload(
    resolver = contentResolver,
    request = request
)

when (validation) {
    is RecordingUploader.ValidationResult.Valid -> {
        if (validation.isTest) {
            Log.i("Upload", "Test number: ${validation.number?.name}")
        }
        when (uploadResult) {
            is Api.Upload.Ok -> Log.i("Upload", "Success: ID ${uploadResult.id}")
            is Api.Upload.Rejected -> Log.e("Upload", "Rejected: ${uploadResult.detail}")
            is Api.Upload.Unauthorized -> Log.e("Upload", "Auth failed: ${uploadResult.detail}")
            is Api.Upload.Retry -> Log.w("Upload", "Retry: ${uploadResult.detail}")
        }
    }
    is RecordingUploader.ValidationResult.Invalid -> {
        Log.w("Upload", "Skipping invalid: ${validation.reason}")
    }
}
```

### Step 4: Handle Test Numbers Specially

Track test vs. production uploads:

```kotlin
fun trackUpload(validation: RecordingUploader.ValidationResult, result: Api.Upload) {
    when {
        validation is RecordingUploader.ValidationResult.Valid && validation.isTest -> {
            // Test upload succeeded
            val number = validation.number?.number ?: "unknown"
            Log.i("TEST_UPLOAD", "Test number $number uploaded")
            // Can log to separate test upload tracker
        }
        validation is RecordingUploader.ValidationResult.Valid -> {
            // Production upload succeeded
            Log.i("PROD_UPLOAD", "Production recording uploaded")
        }
        validation is RecordingUploader.ValidationResult.Invalid -> {
            // Invalid number - was rejected
            Log.i("INVALID_UPLOAD", "${validation.reason}")
        }
    }
}
```

## Testing Checklist

- [ ] Initialize AutoGMap with correct API key and URL
- [ ] Test numbers appear with `"test": true` in API response
- [ ] Local cache populated after first sync
- [ ] Production numbers sync correctly
- [ ] Validation correctly identifies test vs. production numbers
- [ ] Invalid numbers are rejected
- [ ] Upload succeeds for valid (test and production) numbers
- [ ] Sync periodic task runs every 15 minutes
- [ ] Error handling for network issues (retries)
- [ ] Error handling for API changes (graceful degradation)

## API Error Handling

The AutoGMap client handles these scenarios:

| Error | Handling | Action |
|-------|----------|--------|
| Network timeout | Returns `SyncResult.success = false` | Retry next sync |
| HTTP 401/403 | Returns error message | Check API key |
| HTTP 5xx | Returns error message | Retry next sync |
| Invalid JSON | Catches exception | Log error, retry |
| Empty response | Returns 0 numbers | Acceptable (numbers may be empty) |

## Switching Between Test and Production

**In development/staging:**
- AutoGMap returns numbers with `"test": true`
- These are accepted normally
- Can be logged to separate test tracker

**In production:**
- AutoGMap returns only production numbers (`"test": false`)
- Test numbers filtered out by Mansi's API
- All uploads are production

## Configuration

Add to Settings.kt or .env:

```bash
AUTOGMAP_API_KEY=xxx
AUTOGMAP_NUMBERS_URL=https://indev.eko.in/autogmap/api/v1/call-recorder/numbers
AUTOGMAP_SYNC_INTERVAL_MINUTES=15
```

## Next Steps

1. **Confirm API format** with Mansi — verify exact JSON structure
2. **Update AutoGMap.kt** if format differs from assumptions
3. **Integrate into UploadWorker** — add number validation
4. **Test with team numbers** — upload recordings from test numbers
5. **Monitor logs** — verify sync and upload metrics
6. **Production rollout** — deploy when Mansi confirms format

---

**Note:** This implementation assumes test numbers are marked with `"test": true`. Adjust the parsing logic if Mansi's actual format is different.

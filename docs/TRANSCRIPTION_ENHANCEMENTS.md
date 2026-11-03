# Transcription Enhancements

## Overview

This update significantly improves transcription management, adding support for better editing, improved accuracy via Claude AI, and automatic summary regeneration.

## Features

### 1. Enhanced Transcript Editing

**What's new:**
- ✅ Add new dialogue lines at any position in the transcript
- ✅ Edit start/end timestamps of dialogue segments
- ✅ Reorder lines
- ✅ Better validation and error messages

**How to use:**
When editing a recording's transcript:
- **Add new line**: Set `i: null` in the line object with text, speaker, and timestamps
- **Edit timestamps**: Include `start` and `end` fields (seconds, decimal precision)
- **Reorder**: Change the order of lines in the request
- **Remove**: Omit a line from the request (it will be marked as removed)

**Line format:**
```json
{
  "lines": [
    {
      "i": 0,                    // Original index, or null for new lines
      "text": "corrected text",  // Required
      "speaker": "rm",           // "rm" or "csp"
      "voice": "A",              // Single uppercase letter (optional)
      "start": 1.23,             // Start time in seconds (required for new lines)
      "end": 4.56                // End time in seconds (required for new lines)
    },
    {
      "i": null,                 // New line
      "text": "newly added",
      "speaker": "csp",
      "start": 5.0,
      "end": 7.5
    }
  ],
  "checked": ["transcript"]      // Mark as checked after corrections
}
```

### 2. Claude CLI Transcription

**What's new:**
- Primary transcription engine switched to Claude AI for better accuracy
- Automatic fallback to Groq if Claude is unavailable
- Supports all existing features and configurations

**How it works:**
```
Claude STT (if available) 
    ↓ (success or error)
Groq Whisper API (fallback)
```

**Setup:**
- Claude CLI should be available on the system (`claude --version` must work)
- Groq API key still required as fallback (GROQ_API_KEY)
- No additional configuration needed

**Configuration:**
- `STT_ENGINE` automatically selected based on availability
- Both are transparent to the rest of the system

### 3. Auto-Summary Regeneration

**What's new:**
- Summary automatically regenerates when transcript is edited
- No manual "summarize" button needed after edits
- Async operation doesn't block the edit response

**How it works:**
1. User edits and corrects the transcript
2. System saves the changes
3. Async task starts to regenerate summary in background
4. Summary updates based on corrected transcript
5. User sees updated summary on next page refresh

**Technical:**
- Triggered via `_write_summary()` in background thread
- Non-blocking to API response
- Uses same LLM engine as before

### 4. Transcription Accuracy Metrics

**What's new:**
- `transcription_accuracy` field added to all recording responses
- Shows % accuracy based on word error rate (WER)
- Only visible for manually checked transcripts

**Accuracy calculation:**
```
Accuracy = (1 - (errors / total_words)) * 100
```

**Field details:**
- `transcription_accuracy`: number (0-100) or null
- Only populated after manual transcript check
- Based on word-level error rate
- Rounded to 1 decimal place

**API responses:**
- GET `/api/recordings/{rec_id}` - includes accuracy
- GET `/api/recordings` (list) - includes accuracy for all
- Useful for tracking transcription quality over time

## Database Schema Changes

No database schema changes required. System uses existing fields:
- `stt_errors`: Word error count (already calculated)
- `stt_words`: Total words (already calculated)
- `checked_at`: Timestamp of manual check (already present)
- `transcript_json`: Line timestamps (enhanced structure)

## Code Changes

### New Files
- `app/claude_stt.py`: Claude-based STT with Groq fallback

### Modified Files
- `app/recordings.py`:
  - Enhanced `save_edits()` function
  - Added `transcription_accuracy()` function
  - Added `add_transcription_accuracy()` helper
  - Changed STT engine to `claude_stt` with fallback

- `app/main.py`:
  - Updated `RecordingEditBody` docstring
  - Added accuracy to `get_recording()` response
  - Added accuracy to `list_recordings()` response

## API Examples

### Editing transcript with new lines

```bash
PATCH /api/recordings/123
{
  "lines": [
    {"i": 0, "text": "corrected", "speaker": "rm", "start": 0.5, "end": 2.1},
    {"i": null, "text": "new line", "speaker": "csp", "start": 2.2, "end": 4.5},
    {"i": 1, "text": "next", "speaker": "rm", "start": 4.6, "end": 6.0}
  ],
  "checked": ["transcript"]
}
```

### Getting recording with accuracy

```bash
GET /api/recordings/123

{
  "id": 123,
  "status": "done",
  "summary": "...",
  "transcription_accuracy": 94.2,  // NEW: % accuracy
  "stt_errors": 3,
  "stt_words": 50,
  "checked_at": 1699000000,
  "checked_by": "user@eko.co.in",
  ...
}
```

### Listing recordings with accuracy

```bash
GET /api/recordings?status=done

{
  "counts": {...},
  "recordings": [
    {
      "id": 123,
      "transcription_accuracy": 94.2,  // NEW: visible in list
      ...
    }
  ]
}
```

## Troubleshooting

**Claude transcription not working:**
- Check Claude CLI is installed: `claude --version`
- System will automatically fallback to Groq
- No manual intervention needed

**Summary not updating after edit:**
- It's async - refresh page after a few seconds
- Check app logs for any errors
- `report_error` field will be set if summary generation fails

**No accuracy shown:**
- Accuracy only appears for checked transcripts
- Mark transcript as checked: `"checked": ["transcript"]`
- Manually checked transcripts get accuracy calculated

## Performance Notes

- Editing response is instant (summary is async)
- Claude transcription may be slower than Groq (more accurate)
- Fallback to Groq is automatic if Claude times out
- Accuracy calculation is very fast (arithmetic only)

## Future Enhancements

Possible future improvements:
- Granular speaker identification with Claude
- Multi-language support improvements
- Confidence scores per line
- Comparison of Claude vs Groq accuracy
- Batch re-transcription with Claude

## Support

For issues with:
- **Editing**: Check line format matches schema above
- **Timestamps**: Use float seconds with decimal precision
- **Accuracy**: Verify transcript is marked as checked
- **Claude**: Ensure CLI is installed and in PATH

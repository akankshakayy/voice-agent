# Uploader app: Employee/DC setup fix and DC consent (2026-11-19)

## Problems fixed

| Problem | Effect | Fix |
|---|---|---|
| The app's "setup finished" check always required an RM | Employee and DC phones showed "Finish setup and tap Save first" and never uploaded, not even after a call | `Settings.isConfigured` checks the id for the phone's mode |
| The app read the employee/DC id at Test connection but never stored it | The fixed check would still fail | `MainActivity` stores `employeeId` / `dcId` |
| The app made up its own DC consent code (random UUID) | The server rejected every DC upload, or let a DC upload through with no consent at all | The server issues the consent code; DC uploads without a valid one get 403 |
| Allowed numbers were compared as exact text | `+919876543210` in the call log did not match `9876543210` in the list, so DC calls were skipped for good | App and server compare the last 10 digits |
| Allowed numbers were only loaded at setup | Numbers the admin added later were skipped for good | The app refreshes them before each DC run |
| A token with no RM was refused | "Any RM" shared tokens could not be created | `create_token()` with no id makes a shared RM token |
| The Users page offered "Any DC" / "Any Employee" tokens | Not supported by the app or server | Removed; DC and employee tokens must name the person |

## DC consent flow

1. The admin adds the DC and their allowed numbers, then creates a DC token on the Users page.
2. On the DC's phone: paste the token, tap **Test connection**, tick the consent box and tap **Save**.
3. Save calls `POST /api/uploader/consent` (upload token auth, DC tokens only). The server stores a row in
   `dc_consents` and returns `consent_token` (`ekoct_...`), which the app keeps in encrypted storage.
4. Every DC upload sends `consent_token`. The server checks it belongs to that DC and is not expired/used, else
   answers **403**. The app then clears its stored consent, stops the run without dropping the file, and shows
   "Setup not finished" until the DC gives consent again.

Consent is only asked for on DC phones. RM and employee phones are unchanged.

## Tests

`tests/test_uploader_modes.py` (10 tests): DC consent required / made-up codes refused / consent tied to its DC /
non-allowed numbers refused / consent endpoint refuses RM, employee and bad tokens / employee and RM uploads
unchanged / shared RM token / token-mode mismatch / number matching with +91, 0 and spaces.

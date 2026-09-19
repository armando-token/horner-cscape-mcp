# Phase C4 Win32 Modal Dialog Decision Table & Fail-Closed Rules

| Modal Type | Window Class | Match Condition | Enforcement Action | Status | Invariant / Safety Directives |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `SPLASH_SCREEN` | `#32770` | Title contains `splash` or `about cscape` | `AUTO_DISMISS_OK` | `success` | Dismiss with IDOK (1) to unblock GUI startup. |
| `SELECT_EDITOR_TYPE` | `#32770` | Title contains `select editor` or Radio 1461 present | `AUTO_SELECT_IEC_DISMISS_OK` | `success` | Select IEC 61131 radio button (`1461`) and confirm with IDOK (1). |
| `NON_FATAL_COMPILATION_ERROR` | `#32770` | Text contains `Non-Fatal Compilation Errors were found` | `BLOCKED_CAPTURE_NO_CLICK` | `blocked` | **Auto-clicking Yes (`6`) strictly forbidden.** Capture screenshot and dismiss cleanly with No (`7`). |
| `HARDWARE_DOWNLOAD_PROMPT` | `#32770` | Title/text contains `download` or Win32 ID `32827`/`33149` | `BLOCKED_HARDWARE_LOCKOUT` | `blocked` | **Absolute Hardware Lockout.** Physical download commands intercepted and blocked fail-closed. |
| `COMMON_SAVE_AS` | `#32770` | Title contains `Save As` | `CONTROLLED_FILE_SAVE` | `success` | Controlled path targeting; prevents baseline container corruption. |
| `FOREIGN_OR_UNRECOGNIZED_MODAL` | `#32770` | Unrecognized modal dialog or foreign PID | `BLOCKED_CAPTURE_FAIL_CLOSED` | `blocked` | Never auto-click; capture diagnostic telemetry and fail closed with IDCANCEL (2). |

## Architectural Invariants
1. **Zero Blind Auto-Yes**: Under no circumstances may an automated script dispatch `IDYES` (`6`) to non-fatal compilation error dialogs.
2. **Fail-Closed Guarantee**: Every unrecognized or safety-critical prompt fails closed (`status: blocked`).
3. **Single GUI Ownership**: Only ONE process may interact with dialog handles on `winsta0\Default`.

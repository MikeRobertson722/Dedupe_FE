---
name: BA Review App - Project Stack and Startup
description: Framework stack, startup commands, Snowflake auth, and test runner details for the BA Review App
type: project
---

Flask 3.0 + AG Grid 32 (client-side, no pagination) + Bootstrap 5.3 + jQuery 3.7 app.
Snowflake backend (account: A1962426119861-QU16513, db: DGO_MA.BA_PROCESS.import_merge_matches, 31,695 records).
Auth: externalbrowser SSO (SNOWFLAKE_AUTHENTICATOR=externalbrowser) — credentials are cached after first browser login, subsequent startups connect silently.

**Startup:** `python app.py` from C:/ClaudeMain/BA_Review_App — serves on http://127.0.0.1:5000

**Test runner:** pytest + playwright (chromium), 16 tests in test_13_inline_editing.py alone, run from project root:
`python -m pytest tests/ -v --timeout=60`
Conftest auto-starts Flask if not already running via `subprocess.Popen`.

**Key architecture note:** `pendingCount` is a JS-only variable tracking unsaved changes. It is updated only from `data.pending_count` in API AJAX responses inside the browser. Calling `/api/update` via `requests` outside the browser does NOT update the frontend's pending state or save button. Test restores that use `api_update_field()` after a successful save (which resets pendingCount to 0) will leave the save button disabled.

**Process-select change guard:** The jQuery `change` handler on `.process-select` has an early-return guard: `if (oldValue === newValue) return;`. If a test hardcodes a target value (e.g. `"Manual Review - DNP"`) and the live data row already has that value, the handler exits immediately — `saveProcessValue`, `pushUndo`, and `updateSaveBtn` are never called. Tests `test_process_change_enables_save_button`, `test_process_change_save_and_verify_db_by_uid`, and `test_process_pushes_to_undo_stack` were all failing for this reason (row 0 already had `"Manual Review - DNP"` in the live dataset). Fix: read the current value first and pick a different target. Pattern:
```python
current_val = original.get('how_to_process', '')
target_val = "Manual Review - DNP" if current_val != "Manual Review - DNP" else "Add new BA and address"
```

**Why:** App migrated from DataTables + server-side pagination to AG Grid client-side; many test selectors are stale as a result.
**How to apply:** Always start the app before running tests and verify SSO token is still valid. Test restores that need the save button to re-enable must use in-browser JS (`page.evaluate`) to trigger the change, not direct API calls. When writing process-select tests, always derive the target value dynamically to avoid the oldValue === newValue early-exit guard.

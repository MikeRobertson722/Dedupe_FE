---
name: BA Review App - Current Test Failure Inventory (2026-04-02 run 1)
description: 6 failures in regression suite as of 2026-04-02; root causes: actions column removed in commits after a752756, no STAGED data in DB, server-side filter state leaks between tests
type: project
---

As of 2026-04-02 (run against HEAD bd4f305), the regression suite is 47 tests: **40 passed, 6 failed, 1 skipped**.

Run time: ~375s

---

## Failure Summary

### FAIL 1: TestArea02_Filters::test_ssn_filter_reset

**Root Cause:** Server-side filter state persistence causes cross-test contamination.

The app saves filter state (SSN filter, score filters, rec filter) to the server via `/api/grid_settings` on every `change` event. `test_ssn_filter_no` sets `ssnFilter=no` and never resets it. When `test_ssn_filter_reset` opens a fresh page, the app loads saved state and restores `ssnFilter=no`. This means the baseline row count (4233) is the SSN=no count, not the ALL count. Then selecting "yes" yields 27462, which is NOT less than 4233 — assertion fails.

**Fix needed:** `test_ssn_filter_no` must reset `$('#ssnFilter').val('')` and call `onExternalFilterChanged()` after its assertion, OR `test_ssn_filter_reset` must explicitly reset filter state to clear before taking its baseline.

**Consistency:** Fails consistently in full suite (always follows test_ssn_filter_no); passes in isolation.

---

### FAIL 2: TestArea03_RecBucketCards::test_each_bucket_card_filters

**Root Cause:** Zero STAGED records in the live Snowflake database.

The test iterates `BUCKETS = ["NEW BA AND NEW ADDRESS", "EXISTING BA ADD NEW ADDRESS", ..., "STAGED", "ALL"]` and asserts `click_rec_card(page, "STAGED")` returns True. The API `/api/stats` confirms STAGED is absent from the recommendations dict — meaning no STAGED records exist and no STAGED card is rendered. `click_rec_card` returns False, triggering `AssertionError: Could not find rec card for 'STAGED'`.

**Fix needed:** Guard with `if rec_counts.get("STAGED", 0) == 0: pytest.skip("No STAGED records in DB")` before the STAGED bucket loop iteration.

---

### FAIL 3: TestArea04_StagedBucketRestrictions::test_staged_cells_not_editable

**Root Cause:** When 0 STAGED rows exist, `click_rec_card(page, "STAGED")` fails silently (returns False, no exception), leaving the grid on ALL view. Non-STAGED rows ARE editable. The test's skip guard only triggers if `rows.count() == 0`, but ALL rows count is >0. Double-clicking source_name opens an editor — assertion fails.

**Fix needed:** Check the return value of `click_rec_card` and skip if it returned False (no STAGED card found).

---

### FAIL 4: TestArea07_EditModal::test_edit_modal_opens
### FAIL 5: TestArea07_EditModal::test_edit_modal_has_data
### FAIL 6: TestArea09_SaveChanges::test_save_changes_resets_count

**Root Cause:** The `actions` column (colId: 'actions') with `btn-outline-primary` Edit buttons was **removed** from the grid column definitions in commits `75fdcb9` ("Ready for User testing") and `5be5a75` ("Sync Show/Hide Columns"). As of HEAD bd4f305, the column does not exist in app.js. `gridApi.setColumnsVisible(['actions'], true)` silently does nothing, and the locator `#matchesGrid .ag-row:first-child .btn-outline-primary` times out after 30s.

The `editRecord()` function still exists in app.js (line 1184) but has no call sites — the edit modal is dead UI.

**Fix needed:** Either:
- Option A: Restore the actions column in app.js (add back `actionsCellRenderer` and the `actions` colId column definition).
- Option B: Wire `editRecord()` to a different trigger (double-click row, context menu, toolbar button).
- Option C: Update tests to trigger the edit modal via `page.evaluate("() => editRecord(<rowId>)")` directly.

Option C is lowest risk for the tests; Option A/B is the production fix.

---

## Key Diagnostic Notes

- `editRecord()` is defined but unreachable in the current UI. `actionsCellRenderer` was removed in commit `75fdcb9`.
- The `actions` column existed in commits up through `a752756` (Writing to STG_BA_MASTER) but was removed in `75fdcb9` (Ready for User testing).
- Filter state (`ssnFilter`, score filters, `activeRecFilter`) is persisted server-side via `saveGridSetting('filter_state', ...)` on every change. Tests must reset filters explicitly after using them to avoid bleeding state into subsequent tests.
- STAGED card only renders if the DB contains STAGED records. The live dataset currently has 0 STAGED rows (all were presumably committed in a prior staging operation).

---

## Previously Fixed (still passing)

- `refreshGridData` now uses `node.setData()` — visual update after S&R replace works.
- `srHighlightMatch` uses `col.visible` (runtime) instead of `colDef.hide` (static) — hidden column reveal works.
- `srReplaceCurrent` skips no-op matches client-side — Replace button is responsive.
- `test_redo_after_undo` — passes with `setTimeout(() => { window._bulkProcessUpdate = false; }, 0)` fix.
- All 17 areas except 2, 3, 4, 7, 9 pass (40/47).

---
name: BA Review App - Test Failure Inventory and Bug Inventory (2026-04-07)
description: Known test suite failures, pre-existing bugs, and newly discovered bugs as of 2026-04-07; autoHeight regression confirmed 2026-04-07
type: project
---

## RESOLVED (2026-04-07 focused UI test)

### autoHeight REGRESSION — FIXED AND VERIFIED
- **Status:** RESOLVED. All test_row_heights_translatey.py tests pass (8/8).
- Row 0: '1655 MCFARLAND BLVD N PMB 149 / KIMBERLY M' = 2 lines, height=40px. CORRECT.
- KENAN JONES (3-line): height=59px. CORRECT.
- autoHeight: true confirmed at app.js line 475.
- fixRowPositions() confirmed at app.js line 706, debounce 30ms.
- No blanking on scroll: test_scroll_blanking_check.py 5/5 PASS.
- ag-center-cols-container height stable at 2424px throughout scroll (not modified by fixRowPositions).

### .bucket-count badges — CONFIRMED EMPTY (known bug, now confirmed selector is also wrong)
- refreshBucketCounts() looks for `.bucket-count[data-bucket]` elements that DO NOT EXIST
  in the current loadStats() HTML template. loadStats() injects count inline in card text
  ("NEEDS REVIEW - 411,488 (95.3%)") with NO separate `.bucket-count` span elements.
  refreshBucketCounts() is effectively dead code on the UI side.
- Zero .bucket-count elements found via Playwright in live page. The function is orphaned.



## Verified Changes (2026-04-07 full test run + skeleton fix 2026-04-07)

### Change 5: Skeleton Row Suppression — VERIFIED (2026-04-07)
- `infiniteInitialRowCount` confirmed as `1` at runtime (via `gridApi.getGridOption`).
- Null guards in `ssnCellRenderer`, `scoreCellRenderer`, `addressLookupCellRenderer`, `checkboxCellRenderer`, `processCellRenderer`, `memoCellRenderer`, and `rowClassRules` all confirmed present and returning `''` on null data.
- Bucket-switch test: 4 buckets × 4 time-points (0ms/100ms/200ms/400ms) = 16 DOM scans — all clean (zero `.ag-row-loading` rows found, zero badges/checkboxes on skeleton rows).
- Rapid switching (3 switches at 50ms intervals): all clean.
- Zero JS console errors during bucket switching.
- Test: `tests/test_skeleton_suppression.py` (standalone, no pytest).

## Verified Changes (2026-04-07 full test run)

### Change 1: 100K Row Cap — VERIFIED
- `/api/matches?length=100` returns exactly 100 rows.
- `/api/matches?length=-1` routes through `BUCKET_CACHE_MAX_ROWS` LIMIT in data_loader.py (line 487).
- `/api/matches?length=200000` capped to 100K by app.py guard (lines 258-259).
- `maxBlocksInCache` in app.js is now 1000 (100 rows/block × 1000 = 100K max).

### Change 2: Null Guards — VERIFIED
- No "Cannot read properties of undefined" errors on initial grid load.
- No "cannot get grid to draw rows while drawing rows" warnings.
- Grid renders rows correctly on page load.
- Scrolling to trigger lazy-loaded rows: no null errors.
- Column sort: no null errors.
- AG Grid deprecation warnings (non-blocking): suppressMenu deprecated, autoHeight/headerCheckbox not supported with IRM — these are expected/pre-existing config warnings.

### Change 3: Approve Flow — VERIFIED
- Single approve via `/api/update`: NEEDS REVIEW decreases by 1, APPROVED increases by 1, record removed from NR filter, record appears in APPROVED filter.
- Bulk approve via `/api/bulk_update` (records format): Same — counts updated, record moves correctly.
- UI approve via browser (Approve Selected button): bulk_update API called, counts updated correctly.
- All test records restored to original state.

### Change 4: Cache Invalidation — VERIFIED
- After `/api/update` with recommendation change: cache mode goes from "cached" to "sql" (mode=sql, bucket=null).
- After `/api/bulk_update`: same invalidation behavior.
- Post-approve `/api/matches` returns correct (non-stale) data.

---

## Known Bug: Bucket Count Badges Empty on First Page Load

**Severity:** Medium (cosmetic — badges show empty until first approve/refresh action)

**Root cause:** `refreshBucketCounts()` fires at document.ready (line 802) BEFORE `loadStats()` creates the `.bucket-count` badge elements. `loadStats()` injects `.bucket-count` spans dynamically into `#recBreakdown` at line 1292. After badges are created, `refreshBucketCounts()` is never called again (until the 5-minute interval or user action). The initial call finds 0 matching `.bucket-count` elements.

**Fix:** Add `refreshBucketCounts()` call inside `loadStats()` after line 1295 (`$('#recBreakdown').html(html)`).

**Evidence:** Playwright browser test: `/api/bucket-counts` returns 200 with correct data, but `.bucket-count` spans are empty. After calling `refreshBucketCounts()` manually via `page.evaluate`, badges fill immediately.

---

## Counter/GridInfo Fix (2026-04-07)

The `updateGridInfo()` JS function now outputs `"X of Y records"` (filtered) or `"Y records"` (no filter). The old format was `"Showing X of Y records"`. Two test helpers had stale regex patterns that matched the old format — both fixed:
- `tests/helpers/wait_helpers.py` — `get_grid_info_counts()`: regex now matches both new formats
- `tests/test_regression_full.py` — `get_grid_counts()`: same fix

Additionally, `app_page` fixture in `conftest.py` and `load_fresh()` in `test_regression_full.py` now wait for `#gridInfo` to show a non-zero count (via `wait_for_function`) before returning — previously they returned as soon as `.ag-row` appeared, but gridInfo was still `"0 records"` at that moment (~400ms behind).

`click_rec_card()` in `test_regression_full.py` now waits for `#gridInfo` to change text after a card click (replacing a flat 700ms sleep).

## test_regression_full.py: 14 failed, 31 passed, 2 skipped (2026-04-07)

Pre-existing failures unchanged since IRM migration. After counter fix, FAIL 1 is resolved:

### ~~FAIL 1: TestArea01_AppStartupDataLoad::test_grid_info_shows_count~~ FIXED
Now passes. Root cause was timing (gridInfo read before successCallback fired) + stale regex in get_grid_counts().

### FAIL 2: TestArea02_Filters::test_ssn_filter_reset
Server-side filter state persistence causes cross-test contamination.

### FAIL 3: TestArea03_RecBucketCards::test_each_bucket_card_filters
Zero STAGED records in live Snowflake database.

### FAIL 4: TestArea04_StagedBucketRestrictions::test_staged_save_btn_disabled
`#saveChangesBtn` selector no longer exists (element removed/renamed).

### FAIL 5: TestArea04_StagedBucketRestrictions::test_staged_cells_not_editable
Follows from 0 STAGED rows.

### FAIL 6: TestArea05_InlineCellEditing::test_edit_enables_save_btn
`forEachNodeAfterFilterAndSort()` returns null with IRM — only iterates loaded blocks.

### FAIL 7: TestArea06_UndoRedo::test_undo_decrements_pending
Same IRM iteration issue — forEachNodeAfterFilterAndSort() returns null.

### FAIL 8-9: TestArea07_EditModal::test_edit_modal_opens / test_edit_modal_has_data
Actions column removed, editRecord() has no call site.

### FAIL 10: TestArea08_ApproveSelected::test_approve_selected
`getDisplayedRowAtIndex(0)?.data` is null — IRM loading rows not yet available.

### FAIL 11: TestArea09_SaveChanges::test_save_changes_resets_count
Depends on removed actions column/edit modal flow.

### FAIL 12-13: TestArea14_Refresh::test_refresh_triggers_reload_api / test_refresh_grid_repopulates
`button:has-text('Refresh')` strict mode violation: TWO "Refresh" buttons exist (navbar `refreshData()` + new `#refreshBtn`). Fix: use `#refreshBtn` selector instead.

### FAIL 14: TestArea17_Download::test_download_triggers_response
`page.expect_event("download")` times out — AG Grid CSV export may not fire browser download event in headless mode.

---

## Key API Architecture Notes

- `/api/matches` sort params: DataTables-format `order[0][column]=0&order[0][dir]=asc&columns[0][data]=source_name`. NOT `sort_col`/`sort_dir`.
- `/api/bulk_update` accepts two payload formats: `{records: [...], recommendation: '...', process_values: {}}` (new UI format) OR legacy `{row_ids: [...], field: '...', value: '...'} `.
- `BUCKET_CACHE_MAX_ROWS = 100_000` in data_loader.py (line 35).
- NEEDS REVIEW bucket (411K rows) always runs in SQL mode (exceeds BUCKET_CACHE_MAX_ROWS), never uses BucketCache. Only small buckets (APPROVED=146, etc.) use the in-memory cache.

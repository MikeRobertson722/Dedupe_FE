---
name: BA Review App - Project Stack and Startup
description: Framework stack, startup commands, Snowflake auth, and test runner details for the BA Review App
type: project
---

Flask 3.0 + AG Grid 32 (Infinite Row Model, server-side pagination via /api/matches) + Bootstrap 5.3 + jQuery 3.7 app.
Snowflake backend (account: A1962426119861-QU16513, db: DGO_MA.BA_PROCESS.import_merge_matches, ~431K records as of 2026-04-07).
Auth: externalbrowser SSO (SNOWFLAKE_AUTHENTICATOR=externalbrowser) — credentials are cached after first browser login, subsequent startups connect silently.

**Startup:** `python app.py` from C:/ClaudeMain/BA_Review_App — serves on http://127.0.0.1:5000

**Python executable:** /c/Python314/python (Python 3.14.2)

**Test runner:** pytest + playwright (chromium), run from project root:
`/c/Python314/python -m pytest tests/ -v --timeout=60`
Conftest auto-starts Flask if not already running via `subprocess.Popen`.

**Key architecture note:** AG Grid uses Infinite Row Model (IRM). Server paginates via /api/matches with DataTables-style params (start, length, order[0][column], order[0][dir], columns[0][data]). BUCKET_CACHE_MAX_ROWS = 100,000.

**Sort params format (DataTables-style):**
`order[0][column]=0&order[0][dir]=asc&columns[0][data]=source_name`
NOT `sort_col`/`sort_dir` query params.

**Bucket cache:** Small buckets (<100K rows) are cached in-memory as BucketCache (pandas DataFrame). Large buckets (NEEDS REVIEW ~411K) always run in SQL mode. `/api/cache-status` shows current cache state.

**Approve flow (as of 2026-04-07):**
- quickApprove(rowId): JS function exists but has NO call site in any column renderer or template. Per-row approve is dead code.
- bulkApprove(): wired to #bulkApproveBtn — requires row checkbox selection first. Sends `{records: [{id, source_id, source_ssn, old_recommendation}], recommendation: 'APPROVED', process_values: {}}` to `/api/bulk_update`.
- Both approve paths call `_invalidate_cache()` on backend, then `refreshGridData()` + `refreshBucketCounts()` on frontend.

**Known bug (unfixed as of 2026-04-07):** Bucket count badges (.bucket-count spans) are EMPTY on initial page load. refreshBucketCounts() fires before loadStats() creates those spans. loadStats() doesn't call refreshBucketCounts() after injecting them. Fix: add refreshBucketCounts() call after line 1295 in app.js.

**Null guard pattern (fixed 2026-04-07):** All cell renderers, value getters, rowClassRules, and getRowId MUST guard with `if (!params.data) return '';` — AG Grid IRM calls these on virtual/loading rows where params.data is undefined.

**Dynamic row heights — VERIFIED WORKING (2026-04-07 focused UI test):**
- `autoHeight: true` present on source_address_recomend column (app.js line 475). CONFIRMED.
- `fixRowPositions()` present at app.js line 706. Debounce 30ms. CONFIRMED.
- Wired to: `onBodyScrollEnd`, `onViewportChanged`, and datasource `successCallback`.
- Implementation: seeds cumY from first visible row's existing translateY, walks rows by index, sets translateY only. Does NOT touch container height.
- test_row_heights_translatey.py: 8/8 PASS (2026-04-07).
- test_scroll_pagedown_pageup.py: 8/8 PASS (2026-04-07).
- test_scroll_blanking_check.py: 5/5 PASS (2026-04-07) — no blanking detected.
- Search input selector: `#quickFilterInput` (300ms debounced `input` event, calls `applyServerFilters()`).

**Page Down/Page Up scroll contiguity verified by tests/test_scroll_pagedown_pageup.py (8/8 PASS, 2026-04-07):**
- onBodyScrollEnd + onViewportChanged both call fixRowPositions() (debounced 50ms).
- 4x PageDown, 4x PageUp, rapid burst (3 quick presses), alternating Down/Up sequence: all contiguous.
- Multi-line rows remain taller than 24px after scrolling (autoHeight preserved).
- Pinned-left rows stay height/translateY aligned with center rows after scrolling.
- Zero console errors during full scroll cycle.

**Deep-scroll IRM contiguity verified by tests/test_deep_scroll_contiguity.py (9/9 PASS, 2026-04-07):**
- Scroll positions tested: 0, 5000, 20000, 50000, 100000 (capped), and multi-jump sequence.
- FINDING: ag-body-viewport scrollHeight grows dynamically as fixRowPositions extends it with each new block.
  At initial load scrollHeight=2424; after incremental scrolling through 511 rows scrollHeight=14424.
  scrollTop=100000 was capped at ~2044 because the container height was only ~2424 at that moment.
  The cap is not a bug — it's expected: the scrollbar grows as new blocks load. Jump scrolls are limited
  by how far the container has grown, not by the full 411K-row dataset.
- FINDING: fixRowPositions correctly handles all rows from new IRM blocks (rows 100+, 200+, 400+, 500+).
  translateY is contiguous at all scroll depths tested. No overlap or gap violations detected.
- FINDING: gridApi.getInfiniteRowCount() reflects only fetched rows (601 after incremental scroll to 12000).
  The full 411K rows are not pre-allocated in the DOM — only fetched blocks appear.
- Block 0/1 boundary (rows 73-150): contiguous when blocks straddle the viewport.
- Pinned-left rows: aligned with center rows at scrollTop=20000 (rows 75-111, 37 rows checked).
- Zero JS console errors during deep-scroll sequence.
- NOTE: `fixRowPositions` seeds cumY from parseTranslateY(rowList[0].el) — relies on AG Grid having set
  the first visible row's translateY correctly before fix runs. This works correctly at all tested depths.

**Row height behavior verified by tests/test_row_heights_translatey.py (8/8 PASS, 2026-04-07):**
- Single-line rows: exactly 24px
- Multi-line rows: 2-line=40px, 3-line=59-77px (font/padding dependent)
- KENAN JONES (3-line): 77px
- translateY contiguous across all 26 rendered rows (no overlap, no gap)
- Pinned-left rows match center row heights and translateY exactly
- Search + clear cycle: contiguous positions restored on full grid reload
- No JS console errors

**onGridReady datasource timing (fixed 2026-04-07):** loadGridData defers setGridOption('datasource', ...) via setTimeout(fn, 0). No extra datasource set in onGridReady.

**Process-select change guard:** jQuery `change` handler on `.process-select` has early-return: `if (oldValue === newValue) return;`. Always derive target value dynamically in tests.

**pendingCount:** JS-only variable. Calling /api/update via requests outside the browser does NOT update frontend pending state. Test restores via direct API calls will NOT re-enable the save button.

**Refresh buttons (two exist):** navbar button with `onclick="refreshData()"` AND new `#refreshBtn` with title "Refresh data from Snowflake". Playwright tests using `button:has-text('Refresh')` will fail with strict mode violation. Use `#refreshBtn` to target the new button.

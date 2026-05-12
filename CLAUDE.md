# CLAUDE.md - Project Guidelines for AI Assistants

## Dynamic Row Heights (AG Grid IRM) - DO NOT CHANGE

The current row height implementation uses `autoHeight: true` on the `source_address_recomend` column combined with a `fixRowPositions()` function that corrects `translateY` positions on every scroll event and after each block load. **Do not modify this approach unless explicitly directed by the user.**

This solution was arrived at after extensive testing of every alternative:
- `getRowHeight` callback: ignored by AG Grid 32 IRM
- `setRowHeight` + `onRowHeightChanged`: not supported in IRM
- `setRowHeight` + `resetRowHeights`: not supported in IRM
- `setRowHeight` + `redrawRows`: changes height but doesn't reposition subsequent rows
- Server-Side Row Model: requires AG Grid Enterprise (project uses Community)

### Two non-negotiable constraints

1. **`fixRowPositions()` must never modify the container height** (`ag-center-cols-container`). A previous version did this and caused grid blanking on scroll because AG Grid detected the container change and triggered a full row wipe.

2. **`fixRowPositions()` must use `requestAnimationFrame`, not `setTimeout`, and must run on `onBodyScroll` (every scroll event), not just `onBodyScrollEnd`.** An earlier version used `setTimeout(fn, 100)` triggered only on scroll-end. The result was a visible "blink" — the user would PageUp/PageDown and ~100-220ms later all rendered rows would jump by up to 3000px at once (a single batched reposition). RAF + onBodyScroll spreads the corrections across the scroll itself, so they collapse into the same frame as the scroll motion and are imperceptible (one frame ≈ 16ms). `tests/test_post_scroll_repaint_trace.py` codifies this: it fails if any row repositioning lands more than 50ms after the last scroll event.

### How it works
1. `autoHeight: true` + `wrapText: true` on the column lets AG Grid expand cell content
2. `--ag-row-height: 24px !important` in `style.css` prevents AG Grid's 42px CSS override
3. `fixRowPositions()` runs on `onBodyScroll` (every scroll event, RAF-throttled), on `onBodyScrollEnd` (final correction), and after each IRM block-load `successCallback`. It rewrites `translateY` on rendered rows only — never the container height.
4. Pinned-left rows (checkbox column) are synced to match center row heights inside the same RAF pass

## Filter state never persists across page loads

The SSN Match, Min/Max Name, Min/Max Addr filters and the active rec-bucket selection **always reset to "All"** on every page load. Column state (order, width, visibility) still persists via `/api/grid_settings`; only `filter_state` is intentionally ignored on load.

Rationale: previously the server returned a saved `filter_state` (e.g. `ssnFilter: "yes"`), the client restored those values during `initGrid`, and the user-visible record count would inconsistently show "496 of 1,538 records" instead of "1,538 records" after a refresh — confusing because the bucket cards still showed 1,538.

The implementation is one line in `static/js/app.js` near the `initGrid` call: pass `null` for `filter_state` regardless of what the server returned. The regression test in `tests/test_filters_reset_on_load.py` seeds `ssnFilter: "yes"` on the server, reloads the page, and asserts that the SSN dropdown is back at "All" and the grid info shows the unfiltered count.

Do not re-enable filter persistence without explicit user direction.

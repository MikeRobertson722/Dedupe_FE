# CLAUDE.md - Project Guidelines for AI Assistants

## Dynamic Row Heights (AG Grid IRM) - DO NOT CHANGE

The current row height implementation uses `autoHeight: true` on the `source_address_recomend` column combined with a `fixRowPositions()` function that corrects `translateY` positions after each block load and scroll event. **Do not modify this approach unless explicitly directed by the user.**

This solution was arrived at after extensive testing of every alternative:
- `getRowHeight` callback: ignored by AG Grid 32 IRM
- `setRowHeight` + `onRowHeightChanged`: not supported in IRM
- `setRowHeight` + `resetRowHeights`: not supported in IRM
- `setRowHeight` + `redrawRows`: changes height but doesn't reposition subsequent rows
- Server-Side Row Model: requires AG Grid Enterprise (project uses Community)

Critical implementation detail: `fixRowPositions()` must **never modify the container height** (`ag-center-cols-container`). A previous version did this and caused grid blanking on scroll because AG Grid detected the container change and triggered a full row wipe.

### How it works
1. `autoHeight: true` + `wrapText: true` on the column lets AG Grid expand cell content
2. `--ag-row-height: 24px !important` in `style.css` prevents AG Grid's 42px CSS override
3. `fixRowPositions()` runs after `successCallback` and on `onBodyScrollEnd`/`onViewportChanged` to fix `translateY` on rendered rows only
4. Pinned-left rows (checkbox column) are synced to match center row heights

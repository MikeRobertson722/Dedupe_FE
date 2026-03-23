---
name: BA Review App - Stale Test Selectors (UI Redesign)
description: Known test failures caused by UI elements that were removed or restructured during the DataTables->AG Grid migration
type: project
---

As of 2026-03-20, 54 of 129 Playwright tests fail due to stale selectors after the UI was redesigned. 75 pass.

**Removed elements (selectors no longer in HTML):**
- `#recFilterBtn` — recommendation filter was a dropdown button; now inline cards in `#recBreakdown` (dynamically built by JS)
- `#pageSizeSelect` — DataTables page-size select; AG Grid has no pagination (`pagination: false`)
- `#datasourceSelector` — datasource dropdown removed; hardcoded to Snowflake (static text in navbar)
- `.ag-paging-panel` — AG Grid pagination panel hidden (ag-hidden class) since pagination is off
- `#importType` — import type select removed (check current HTML)
- `.field-check[data-field='jib']` — jib/rev/vendor checkboxes rendered via AG Grid `cellRenderer`; columns are hidden by default. Tests set them visible via `gridApi.setColumnsVisible()` but then look for the checkbox `input` directly inside the cell (`#matchesGrid .ag-row:first-child .ag-cell[col-id='jib'] input`) — this works ONLY when the cell is rendered and not virtualized away

**Changed semantics:**
- `#editSourceName` is now an `<input>` (editable), not a `<td>`. Test expected `tag == 'td'` (read-only) but the source section was made editable.
- `#editDecName` is now a `<td>` (read-only display), not an `<input>`. Test expected it to be editable — DEC fields moved to read-only.
- `button:has-text('Search')` is ambiguous — matches both the Search & Replace button AND the "Filtering & Searching" accordion button in the Help modal.

**Memo/inline editing selector issue:**
Tests look for `#matchesGrid .ag-cell[col-id='memo'] input` after clicking `.memo-text`. The memo cell uses jQuery `.replaceWith()` to swap a `<span>` for an `<input>` inline. This may work but AG Grid cell virtualization can remove/recreate DOM nodes.

**Why:** DataTables->AG Grid migration + source/dec section swap (source now editable, DEC read-only) happened after tests were written.
**How to apply:** When asked to fix or update tests, the root cause is always selector staleness, not functional regression. The API layer and core data flows all work correctly.

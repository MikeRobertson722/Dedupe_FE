"""
Test: autoHeight: true column property with AG Grid IRM.

The new approach:
- style.css: --ag-row-height: 24px !important  (beats AG Grid's injected 42px)
- source_address_recomend column: autoHeight: true, wrapText: true
- gridOptions: rowHeight: 24 (default for single-line rows)
- NO getRowHeight callback, NO setRowHeight, NO redrawRows calls

autoHeight: true tells AG Grid to measure each cell's content height and
expand that row to fit. This test verifies:
1. Single-line rows render at 24px (CSS var default wins, no expansion needed).
2. The KENAN JONES row with a 3-line address renders TALLER than 24px.
3. The multi-line cell contains <br> tags (cell renderer fired correctly).
4. translateY positions are contiguous (no overlap).
5. No console errors.

NOTE: autoHeight in IRM may require AG Grid to render/measure cells before
applying height — allow adequate settle time after the grid loads.
"""

import re
import time
import pytest
from playwright.sync_api import sync_playwright, ConsoleMessage

BASE_URL = "http://127.0.0.1:5000"
TRANSLATE_RE = re.compile(r'translateY\((-?[\d.]+)px\)')


def _wait_for_grid_info(page, timeout_ms=25000):
    page.wait_for_function(
        "() => { var t = document.querySelector('#gridInfo'); "
        "return t && /\\d/.test(t.innerText) && t.innerText !== '0 records'; }",
        timeout=timeout_ms,
    )


def _wait_for_rows(page, min_rows=1, timeout_ms=20000):
    page.wait_for_function(
        f"document.querySelectorAll('.ag-row:not(.ag-row-loading)').length >= {min_rows}",
        timeout=timeout_ms,
    )


def _collect_row_positions(page):
    """
    Collect translateY and computed height for all visible non-loading ag-rows.
    Returns list of dicts sorted by rowIndex.
    """
    return page.evaluate("""
    () => {
        var container = document.querySelector('.ag-center-cols-container') || document.body;
        var rows = Array.from(container.querySelectorAll('div.ag-row:not(.ag-row-loading)'));
        var results = [];
        for (var i = 0; i < rows.length; i++) {
            var el = rows[i];
            var transform = el.style.transform || '';
            var match = transform.match(/translateY\\((-?[\\d.]+)px\\)/);
            var translateY = match ? parseFloat(match[1]) : null;
            var computedH = parseFloat(window.getComputedStyle(el).height);
            var inlineH = el.style.height;
            var rowIndex = parseInt(el.getAttribute('row-index'));
            var addrCell = el.querySelector('[col-id="source_address_recomend"]');
            var brCount = addrCell ? addrCell.querySelectorAll('br').length : 0;
            var cellText = addrCell ? (addrCell.innerText || '').substring(0, 100) : '';
            var cellHTML = addrCell ? addrCell.innerHTML.substring(0, 300) : '';
            results.push({
                rowIndex: rowIndex,
                translateY: translateY,
                transform: transform,
                height: computedH,
                inlineHeight: inlineH,
                brCount: brCount,
                cellText: cellText,
                cellHTML: cellHTML
            });
        }
        results.sort(function(a, b) { return a.rowIndex - b.rowIndex; });
        return results;
    }
    """)


def _check_contiguity(rows):
    """
    Verify each row's translateY == previous row's translateY + previous row's height.
    Returns list of overlap dicts. Empty list means PASS.
    """
    overlaps = []
    for i in range(1, len(rows)):
        prev = rows[i - 1]
        curr = rows[i]
        if prev["translateY"] is None or curr["translateY"] is None:
            continue
        if curr["rowIndex"] != prev["rowIndex"] + 1:
            continue  # Non-adjacent rows — skip gap check
        expected = prev["translateY"] + prev["height"]
        if abs(curr["translateY"] - expected) > 1.0:
            overlaps.append({
                "row_index": curr["rowIndex"],
                "expected_translateY": expected,
                "actual_translateY": curr["translateY"],
                "delta": curr["translateY"] - expected,
                "prev_index": prev["rowIndex"],
                "prev_height": prev["height"],
                "prev_translateY": prev["translateY"],
            })
    return overlaps


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: Initial page load — single-line rows at 24px, contiguous translateY
# ─────────────────────────────────────────────────────────────────────────────
def test_initial_load_single_line_rows_24px():
    """
    On initial load (NEEDS REVIEW bucket), all visible rows should be single-line
    and render at 24px. translateY positions must be contiguous.
    """
    console_errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        def on_console(msg: ConsoleMessage):
            if msg.type in ("error", "warning"):
                console_errors.append({"type": msg.type, "text": msg.text})

        page.on("console", on_console)
        page.goto(BASE_URL, timeout=30000)
        page.wait_for_selector("#matchesGrid .ag-row", timeout=30000)
        _wait_for_grid_info(page)
        _wait_for_rows(page, min_rows=5)
        # autoHeight needs time to measure and apply — wait for layout to settle
        time.sleep(1.5)

        rows = _collect_row_positions(page)

        print(f"\n[INITIAL LOAD] Visible non-loading rows: {len(rows)}")
        for r in rows[:12]:
            print(f"  row-index={r['rowIndex']}  translateY={r['translateY']}px  "
                  f"height={r['height']}px  inline-h={r['inlineHeight']!r}  "
                  f"brs={r['brCount']}")

        # --- Assertion 1: At least 5 rows ---
        assert len(rows) >= 5, f"Expected >= 5 rows on load, got {len(rows)}"

        # --- Assertion 2: All rows use translateY (IRM layout) ---
        missing_ty = [r for r in rows if r["translateY"] is None]
        assert len(missing_ty) == 0, (
            f"{len(missing_ty)} rows missing translateY: "
            f"{[(r['rowIndex'], r['transform']) for r in missing_ty[:5]]}"
        )

        # --- Assertion 3: Single-line rows are 24px ---
        single_line = [r for r in rows if r["brCount"] == 0]
        wrong_height = [r for r in single_line if abs(r["height"] - 24) > 1]
        if wrong_height:
            print(f"\n[FAIL] {len(wrong_height)} single-line rows not at 24px:")
            for r in wrong_height:
                print(f"  row-index={r['rowIndex']}  height={r['height']}px  "
                      f"inline-h={r['inlineHeight']!r}")
        assert len(wrong_height) == 0, (
            f"{len(wrong_height)} single-line rows wrong height (expected 24px): "
            f"{[(r['rowIndex'], r['height']) for r in wrong_height]}"
        )

        # --- Assertion 4: Contiguous translateY ---
        overlaps = _check_contiguity(rows)
        if overlaps:
            print(f"\n[FAIL] {len(overlaps)} translateY overlap(s):")
            for ov in overlaps:
                print(f"  row-index={ov['row_index']}: expected={ov['expected_translateY']}px "
                      f"actual={ov['actual_translateY']}px delta={ov['delta']:+.1f}px")
        assert len(overlaps) == 0, (
            f"{len(overlaps)} non-contiguous translateY rows: "
            f"{[(o['row_index'], o['expected_translateY'], o['actual_translateY']) for o in overlaps]}"
        )

        # --- Assertion 5: No row-height console errors ---
        height_errors = [e for e in console_errors
                         if any(kw in e["text"].lower() for kw in
                                ["rowheight", "row height", "autoheight"])]
        print(f"\n[INFO] All console errors/warnings ({len(console_errors)}):")
        for e in console_errors:
            print(f"  [{e['type'].upper()}] {e['text'][:200]}")
        assert len(height_errors) == 0, (
            f"Console errors related to row heights on initial load: {height_errors}"
        )

        browser.close()


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: KENAN JONES search — multi-line row expands beyond 24px
# ─────────────────────────────────────────────────────────────────────────────
def test_kenan_jones_autoheight_expands():
    """
    Search for KENAN JONES. The row with 'PO BOX 701\\nKENAN JONES...\\n& ASSET MGMTCO - AGENT'
    must be taller than 24px (autoHeight: true should expand it to fit 3 lines).
    Single-line rows must stay at 24px.
    translateY positions must remain contiguous.

    KEY QUESTION: does autoHeight: true actually expand rows in AG Grid 32 IRM?
    """
    console_errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        def on_console(msg: ConsoleMessage):
            if msg.type in ("error", "warning"):
                console_errors.append({"type": msg.type, "text": msg.text})

        page.on("console", on_console)
        page.goto(BASE_URL, timeout=30000)
        page.wait_for_selector("#matchesGrid .ag-row", timeout=30000)
        _wait_for_grid_info(page)
        _wait_for_rows(page, min_rows=1)

        # Search for KENAN JONES
        search_box = page.locator("#quickFilterInput")
        search_box.wait_for(state="visible", timeout=10000)
        search_box.fill("")
        time.sleep(0.4)
        search_box.fill("KENAN JONES")
        page.wait_for_function(
            "document.querySelectorAll('.ag-row:not(.ag-row-loading)').length >= 1",
            timeout=20000,
        )
        # autoHeight needs extra time to measure and apply heights after datasource reload
        time.sleep(1.5)

        rows = _collect_row_positions(page)

        print(f"\n[KENAN JONES] Visible rows: {len(rows)}")
        for r in rows:
            print(f"  row-index={r['rowIndex']}  translateY={r['translateY']}px  "
                  f"height={r['height']}px  brs={r['brCount']}  "
                  f"text={r['cellText']!r}")
            if r['brCount'] > 0:
                print(f"    cellHTML={r['cellHTML'][:200]}")

        assert len(rows) >= 1, "No rows found after KENAN JONES search"

        # --- Assertion 1: Find row with PO BOX 701 ---
        target_rows = [r for r in rows if "PO BOX 701" in r["cellText"]]
        print(f"\n[INFO] Rows containing 'PO BOX 701': {len(target_rows)}")
        assert len(target_rows) >= 1, (
            f"Expected to find 'PO BOX 701' row in results. "
            f"Available cell texts: {[r['cellText'] for r in rows]}"
        )

        for tr in target_rows:
            print(f"\n[TARGET] row-index={tr['rowIndex']}  height={tr['height']}px  "
                  f"brCount={tr['brCount']}  cellHTML={tr['cellHTML'][:200]}")

            # --- Assertion 2: Multi-line row is TALLER than 24px ---
            # autoHeight: true should expand the row beyond the 24px default
            # For 3 lines with line-height 1.3 * ~16px font ≈ 20.8px/line → ~63px
            # For 3 lines at 18px (old calcRowHeight) → 60px
            # Either way, should be significantly > 24px
            assert tr["height"] > 24, (
                f"KENAN JONES multi-line row (index={tr['rowIndex']}) height={tr['height']}px. "
                f"Expected > 24px (autoHeight should expand it). "
                f"autoHeight: true may NOT be working in AG Grid 32 IRM. "
                f"brCount={tr['brCount']}  inlineH={tr['inlineHeight']!r}"
            )
            print(f"  [PASS] Row height {tr['height']}px > 24px — autoHeight is expanding the row.")

            # --- Assertion 3: Cell contains <br> tags (3 lines = 2 <br>s) ---
            assert tr["brCount"] >= 2, (
                f"Expected >= 2 <br> tags in 3-line cell, got {tr['brCount']}. "
                f"cellHTML: {tr['cellHTML'][:300]}"
            )
            print(f"  [PASS] brCount={tr['brCount']} >= 2 — cell renderer split lines correctly.")

        # --- Assertion 4: Single-line rows stay at 24px ---
        single_line = [r for r in rows
                       if r["brCount"] == 0 and r["cellText"].strip() and r["height"] > 0]
        wrong_single = [r for r in single_line if abs(r["height"] - 24) > 1]
        if wrong_single:
            print(f"\n[FAIL] {len(wrong_single)} single-line rows not at 24px:")
            for r in wrong_single:
                print(f"  row-index={r['rowIndex']}  height={r['height']}px")
        assert len(wrong_single) == 0, (
            f"{len(wrong_single)} single-line rows wrong height (expected 24px): "
            f"{[(r['rowIndex'], r['height']) for r in wrong_single]}"
        )

        # --- Assertion 5: Contiguous translateY (no overlap) ---
        if len(rows) >= 2:
            overlaps = _check_contiguity(rows)
            if overlaps:
                print(f"\n[FAIL] {len(overlaps)} translateY overlap(s) after KENAN JONES search:")
                for ov in overlaps:
                    print(f"  row-index={ov['row_index']}: expected={ov['expected_translateY']}px "
                          f"actual={ov['actual_translateY']}px delta={ov['delta']:+.1f}px")
            assert len(overlaps) == 0, (
                f"{len(overlaps)} non-contiguous translateY rows after KENAN JONES search: "
                f"{[(o['row_index'], o['expected_translateY'], o['actual_translateY']) for o in overlaps]}"
            )
        else:
            print("[NOTE] Only 1 row — skipping contiguity check.")

        # --- Assertion 6: No console errors ---
        print(f"\n[INFO] All console errors/warnings ({len(console_errors)}):")
        for e in console_errors:
            print(f"  [{e['type'].upper()}] {e['text'][:200]}")
        assert len(console_errors) == 0, (
            f"Unexpected console errors: {console_errors}"
        )

        browser.close()


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: Clear search after KENAN JONES — no stale translateY, 24px rows
# ─────────────────────────────────────────────────────────────────────────────
def test_clear_search_returns_to_24px_no_overlap():
    """
    After loading the KENAN JONES multi-line row, clear the search filter.
    Verify the full grid view re-renders with 24px single-line rows and
    contiguous translateY positions (no stale offsets from the expanded row).
    """
    console_errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        def on_console(msg: ConsoleMessage):
            if msg.type in ("error", "warning"):
                console_errors.append({"type": msg.type, "text": msg.text})

        page.on("console", on_console)
        page.goto(BASE_URL, timeout=30000)
        page.wait_for_selector("#matchesGrid .ag-row", timeout=30000)
        _wait_for_grid_info(page)
        _wait_for_rows(page, min_rows=5)

        search_box = page.locator("#quickFilterInput")
        search_box.wait_for(state="visible", timeout=10000)

        # Step 1: Search KENAN JONES
        search_box.fill("")
        time.sleep(0.4)
        search_box.fill("KENAN JONES")
        page.wait_for_function(
            "document.querySelectorAll('.ag-row:not(.ag-row-loading)').length >= 1",
            timeout=20000,
        )
        time.sleep(1.5)

        # Step 2: Clear search
        search_box.fill("")
        page.wait_for_function(
            "document.querySelectorAll('.ag-row:not(.ag-row-loading)').length >= 5",
            timeout=20000,
        )
        _wait_for_grid_info(page)
        time.sleep(1.5)

        rows = _collect_row_positions(page)

        print(f"\n[CLEAR SEARCH] Rows after returning to full view: {len(rows)}")
        for r in rows[:12]:
            print(f"  row-index={r['rowIndex']}  translateY={r['translateY']}px  "
                  f"height={r['height']}px  brs={r['brCount']}")

        assert len(rows) >= 5, f"Expected >= 5 rows after clear search, got {len(rows)}"

        # All rows have translateY
        missing_ty = [r for r in rows if r["translateY"] is None]
        assert len(missing_ty) == 0, (
            f"{len(missing_ty)} rows missing translateY after clear search"
        )

        # Single-line rows at 24px
        single_line = [r for r in rows if r["brCount"] == 0]
        wrong_height = [r for r in single_line if abs(r["height"] - 24) > 1]
        assert len(wrong_height) == 0, (
            f"{len(wrong_height)} single-line rows wrong height after clear search "
            f"(expected 24px): {[(r['rowIndex'], r['height']) for r in wrong_height]}"
        )

        # Contiguous translateY
        overlaps = _check_contiguity(rows)
        if overlaps:
            print(f"\n[FAIL] {len(overlaps)} translateY overlap(s) after clear search:")
            for ov in overlaps:
                print(f"  row-index={ov['row_index']}: expected={ov['expected_translateY']}px "
                      f"actual={ov['actual_translateY']}px delta={ov['delta']:+.1f}px")
        assert len(overlaps) == 0, (
            f"{len(overlaps)} non-contiguous translateY after clear search: "
            f"{[(o['row_index'], o['expected_translateY'], o['actual_translateY']) for o in overlaps]}"
        )

        print(f"\n[INFO] All console errors/warnings ({len(console_errors)}):")
        for e in console_errors:
            print(f"  [{e['type'].upper()}] {e['text'][:200]}")

        browser.close()


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: Verify AG Grid actually sees autoHeight: true on the column def
# ─────────────────────────────────────────────────────────────────────────────
def test_column_def_has_autoheight():
    """
    Verify via JS that the source_address_recomend column definition has
    autoHeight: true as AG Grid knows it (via getColumnDef API).
    This is a config-level sanity check — if the column def is wrong,
    no amount of CSS will make rows expand.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        page.goto(BASE_URL, timeout=30000)
        page.wait_for_selector("#matchesGrid .ag-row", timeout=30000)

        col_def = page.evaluate("""
        () => {
            var col = gridApi.getColumnDef('source_address_recomend');
            if (!col) return { error: 'column not found' };
            return {
                field: col.field,
                autoHeight: col.autoHeight,
                wrapText: col.wrapText,
                colId: col.colId
            };
        }
        """)

        print(f"\n[COL DEF] source_address_recomend: {col_def}")

        assert "error" not in col_def, f"Column not found: {col_def}"
        assert col_def["autoHeight"] is True, (
            f"Column 'source_address_recomend' does NOT have autoHeight: true. "
            f"Got: autoHeight={col_def['autoHeight']!r}. "
            f"Full colDef: {col_def}"
        )
        assert col_def["wrapText"] is True, (
            f"Column 'source_address_recomend' missing wrapText: true. Got: {col_def}"
        )

        print(f"  [PASS] autoHeight={col_def['autoHeight']}, wrapText={col_def['wrapText']}")

        browser.close()


# ─────────────────────────────────────────────────────────────────────────────
# Test 5: CSS variable is 24px with !important
# ─────────────────────────────────────────────────────────────────────────────
def test_css_row_height_var_is_24px_important():
    """
    Verify that the --ag-row-height CSS custom property resolves to 24px
    on the grid element, and that the !important flag wins over AG Grid's
    injected inline stylesheet (which injects 42px via calc(var(--ag-grid-size)*7)).
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        page.goto(BASE_URL, timeout=30000)
        page.wait_for_selector("#matchesGrid .ag-row", timeout=30000)

        css_result = page.evaluate("""
        () => {
            var gridEl = document.querySelector('#matchesGrid');
            if (!gridEl) return { error: 'grid element not found' };
            var computed = window.getComputedStyle(gridEl);
            var val = computed.getPropertyValue('--ag-row-height').trim();
            return {
                value: val,
                gridElClass: gridEl.className.substring(0, 80)
            };
        }
        """)

        print(f"\n[CSS VAR] --ag-row-height result: {css_result}")

        assert "error" not in css_result, f"Grid element not found: {css_result}"
        # The value should be 24px (the !important rule wins)
        val = css_result["value"]
        assert "24px" in val, (
            f"--ag-row-height CSS var is '{val}', expected '24px'. "
            f"The !important rule in style.css may not be winning over AG Grid's "
            f"injected stylesheets. This would cause all rows to render at 42px."
        )
        print(f"  [PASS] --ag-row-height = '{val}' (24px wins with !important)")

        browser.close()

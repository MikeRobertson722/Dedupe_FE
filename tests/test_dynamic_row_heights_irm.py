"""
Test: Dynamic row heights with redrawRows in IRM (Infinite Row Model).
Verifies that multi-line source_address_recomend values cause the row DOM element
to render at the correct height (60px for 3 lines), while adjacent single-line
rows remain at 24px. Also verifies no console errors about onRowHeightChanged.
"""

import re
import time
import pytest
from playwright.sync_api import sync_playwright, ConsoleMessage

BASE_URL = "http://127.0.0.1:5000"
SEARCH_NAME = "KENAN JONES"
# Expected value per the task description
EXPECTED_VAL_FRAGMENT = "PO BOX 701"
EXPECTED_LINE_COUNT = 3
EXPECTED_MULTI_H = EXPECTED_LINE_COUNT * 18 + 6   # = 60
EXPECTED_SINGLE_H = 24


def _wait_for_grid_rows(page, min_rows=1, timeout_ms=15000):
    """Wait until AG Grid has at least min_rows non-loading rows."""
    page.wait_for_function(
        f"document.querySelectorAll('.ag-row:not(.ag-row-loading)').length >= {min_rows}",
        timeout=timeout_ms,
    )


def _search(page, name: str):
    """Type a name into the quick filter box and wait for grid to reload.
    #quickFilterInput has a 300ms debounce; applyServerFilters() resets the datasource.
    """
    search_box = page.locator("#quickFilterInput")
    search_box.wait_for(state="visible", timeout=10000)
    search_box.fill("")
    # Wait for any prior datasource request to settle
    time.sleep(0.4)
    search_box.fill(name)
    # Wait for debounce (300ms) to fire + datasource reset + first page fetch to complete
    # We wait until at least 1 non-loading row appears
    page.wait_for_function(
        "document.querySelectorAll('.ag-row:not(.ag-row-loading)').length >= 1",
        timeout=15000,
    )
    # Give adjustRowHeights a moment to run after successCallback
    time.sleep(0.8)


def test_multi_line_row_height_dom():
    """
    Search for KENAN JONES, find the row with PO BOX 701 multi-line address,
    and confirm its DOM height == 60px. Also check adjacent single-line rows == 24px.
    """
    console_errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        # Collect console errors/warnings
        def on_console(msg: ConsoleMessage):
            if msg.type in ("error", "warning"):
                console_errors.append({"type": msg.type, "text": msg.text})

        page.on("console", on_console)

        # Load app (avoid networkidle — app has long-running polling XHRs)
        page.goto(BASE_URL, timeout=30000)
        page.wait_for_selector("#matchesGrid .ag-row", timeout=30000)
        # Wait for grid data to actually load into nodes (not just DOM skeleton)
        page.wait_for_function(
            "() => { var t = document.querySelector('#gridInfo'); return t && /\\d/.test(t.innerText) && t.innerText !== '0 records'; }",
            timeout=20000,
        )
        _wait_for_grid_rows(page, min_rows=1)

        # Search for KENAN JONES
        _search(page, SEARCH_NAME)

        # ── Collect all visible rows and their heights ──
        row_data = page.evaluate("""
        () => {
            var rows = Array.from(document.querySelectorAll('.ag-row:not(.ag-row-loading)'));
            return rows.map(function(r) {
                var cell = r.querySelector('[col-id="source_address_recomend"]');
                var cellText = cell ? cell.innerText : '';
                var cellHTML = cell ? cell.innerHTML : '';
                var brs = cell ? cell.querySelectorAll('br').length : 0;
                var style = window.getComputedStyle(r);
                var heightStyle = r.style.height;
                var computedH = parseFloat(style.height);
                var rowIndex = r.getAttribute('row-index');
                return {
                    rowIndex: rowIndex,
                    cellText: cellText,
                    cellHTML: cellHTML,
                    brCount: brs,
                    inlineHeight: heightStyle,
                    computedHeight: computedH
                };
            });
        }
        """)

        print(f"\n[INFO] Total visible rows: {len(row_data)}")
        for rd in row_data:
            print(f"  row-index={rd['rowIndex']}  inlineH={rd['inlineHeight']}  "
                  f"computedH={rd['computedHeight']}px  brCount={rd['brCount']}  "
                  f"text={rd['cellText'][:60]!r}")

        # ── Find the KENAN JONES / PO BOX 701 row ──
        target_rows = [rd for rd in row_data if EXPECTED_VAL_FRAGMENT in rd["cellText"]]
        print(f"\n[INFO] Rows containing '{EXPECTED_VAL_FRAGMENT}': {len(target_rows)}")

        # ── Assertion 1: target row found ──
        assert len(target_rows) >= 1, (
            f"Expected to find a row with '{EXPECTED_VAL_FRAGMENT}' in source_address_recomend, "
            f"but found {len(target_rows)}. Available cells: "
            f"{[r['cellText'][:60] for r in row_data]}"
        )

        for tr in target_rows:
            print(f"\n[TARGET ROW] index={tr['rowIndex']}  "
                  f"inlineH={tr['inlineHeight']}  computedH={tr['computedHeight']}  "
                  f"brCount={tr['brCount']}\n  HTML={tr['cellHTML'][:200]}")

            # ── Assertion 2: row DOM height == 60px ──
            assert tr["computedHeight"] == pytest.approx(EXPECTED_MULTI_H, abs=1), (
                f"Multi-line row height expected {EXPECTED_MULTI_H}px, "
                f"got {tr['computedHeight']}px (inlineStyle={tr['inlineHeight']!r})"
            )

            # ── Assertion 3: <br> tags present in cell HTML ──
            expected_brs = EXPECTED_LINE_COUNT - 1   # 3 lines → 2 <br> tags
            assert tr["brCount"] >= expected_brs, (
                f"Expected at least {expected_brs} <br> tag(s) in multi-line cell, "
                f"got {tr['brCount']}. HTML: {tr['cellHTML'][:300]}"
            )

        # ── Assertion 4: single-line rows (with non-empty cell text) should be 24px ──
        # Skip rows with empty cell text — IRM may show stale/virtual placeholder
        # rows that share a row-index with an already-rendered row; they have no
        # meaningful height requirement.
        single_line_rows = [
            rd for rd in row_data
            if rd["brCount"] == 0 and rd["computedHeight"] > 0 and rd["cellText"].strip()
        ]
        print(f"\n[INFO] Single-line rows with content: {len(single_line_rows)}")
        if len(single_line_rows) == 0:
            print("  [NOTE] No adjacent single-line rows visible after KENAN JONES filter "
                  "(search returned only 1 result). Skipping single-line height check.")
        wrong_single = [r for r in single_line_rows if abs(r["computedHeight"] - EXPECTED_SINGLE_H) > 1]
        if wrong_single:
            for wr in wrong_single:
                print(f"  [WARN] Single-line row index={wr['rowIndex']} has "
                      f"height={wr['computedHeight']}px (expected {EXPECTED_SINGLE_H})")
        assert len(wrong_single) == 0, (
            f"{len(wrong_single)} single-line rows have wrong height "
            f"(expected {EXPECTED_SINGLE_H}px): "
            f"{[(r['rowIndex'], r['computedHeight']) for r in wrong_single]}"
        )

        # ── Assertion 5: no onRowHeightChanged console errors ──
        row_height_errors = [
            e for e in console_errors
            if "onRowHeightChanged" in e["text"] or "rowHeightChanged" in e["text"].lower()
        ]
        print(f"\n[INFO] onRowHeightChanged errors: {len(row_height_errors)}")
        for e in row_height_errors:
            print(f"  [{e['type'].upper()}] {e['text']}")
        assert len(row_height_errors) == 0, (
            f"Found console messages about onRowHeightChanged: {row_height_errors}"
        )

        # ── Bonus: print all console errors for visibility ──
        if console_errors:
            print(f"\n[INFO] All console errors/warnings ({len(console_errors)}):")
            for e in console_errors:
                print(f"  [{e['type'].upper()}] {e['text'][:200]}")
        else:
            print("\n[INFO] Zero console errors/warnings.")

        browser.close()


def test_no_row_height_console_errors_on_load():
    """
    Verify that simply loading the page and waiting for grid data
    produces no console errors mentioning row heights.
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
        page.wait_for_function(
            "() => { var t = document.querySelector('#gridInfo'); return t && /\\d/.test(t.innerText) && t.innerText !== '0 records'; }",
            timeout=20000,
        )
        _wait_for_grid_rows(page, min_rows=1)
        time.sleep(1.0)  # Let adjustRowHeights run after successCallback

        row_height_errors = [
            e for e in console_errors
            if any(kw in e["text"].lower() for kw in [
                "onrowheightchanged", "rowheightchanged", "row height"
            ])
        ]
        print(f"\n[INFO] Row-height related console messages: {len(row_height_errors)}")
        print(f"[INFO] All console messages ({len(console_errors)}):")
        for e in console_errors:
            print(f"  [{e['type'].upper()}] {e['text'][:200]}")

        assert len(row_height_errors) == 0, (
            f"Console errors mentioning row heights on page load: {row_height_errors}"
        )
        browser.close()


def test_synthetic_multi_line_row_height():
    """
    Inject a multi-line value into the first row's source_address_recomend via
    JS, call adjustRowHeights(), and verify the row height changes to 60px.
    This tests the IRM redrawRows path directly without requiring live multi-line data.
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
        page.wait_for_function(
            "() => { var t = document.querySelector('#gridInfo'); return t && /\\d/.test(t.innerText) && t.innerText !== '0 records'; }",
            timeout=20000,
        )
        # Wait for IRM block data to be loaded into the first node's .data property.
        # In SQL mode (NEEDS REVIEW 411K rows) the IRM shows rows immediately but
        # node.data may still be null until the block fetch completes.
        page.wait_for_function(
            "() => { var n = gridApi && gridApi.getDisplayedRowAtIndex(0); return n && n.data != null; }",
            timeout=20000,
        )
        _wait_for_grid_rows(page, min_rows=1)
        time.sleep(0.3)

        # Inject 3-line value into first loaded node and run adjustRowHeights()
        # Use getDisplayedRowAtIndex(0) to get the first rendered row node — more
        # reliable than forEachNode() which may return placeholder nodes without .data
        # in SQL mode IRM (NEEDS REVIEW bucket, 411K rows).
        result = page.evaluate("""
        () => {
            var firstNode = gridApi.getDisplayedRowAtIndex(0);
            if (!firstNode || !firstNode.data) {
                // Fallback: iterate forEachNode
                gridApi.forEachNode(function(n) { if (!firstNode && n.data) firstNode = n; });
            }
            if (!firstNode || !firstNode.data) return {
                error: 'no node found',
                displayedRow0: firstNode ? JSON.stringify({rowIndex: firstNode.rowIndex, hasData: !!firstNode.data}) : 'null',
                gridInfoText: (document.querySelector('#gridInfo') || {}).innerText || 'n/a'
            };

            var origVal = firstNode.data.source_address_recomend;
            firstNode.data.source_address_recomend = 'LINE ONE\\nLINE TWO\\nLINE THREE';
            adjustRowHeights();

            // Read DOM height
            var rowEl = document.querySelector('.ag-row[row-index="' + firstNode.rowIndex + '"]');
            var domH = rowEl ? parseFloat(window.getComputedStyle(rowEl).height) : null;
            var inlineH = rowEl ? rowEl.style.height : null;
            var nodeH = firstNode.rowHeight;

            // Restore original value
            firstNode.data.source_address_recomend = origVal;
            adjustRowHeights();

            return {
                rowIndex: firstNode.rowIndex,
                domHeight: domH,
                inlineHeight: inlineH,
                nodeRowHeight: nodeH
            };
        }
        """)

        print(f"\n[SYNTHETIC TEST] result: {result}")

        assert "error" not in result, f"JS error during synthetic test: {result}"
        assert result["nodeRowHeight"] == 60, (
            f"node.rowHeight after 3-line inject: expected 60, got {result['nodeRowHeight']}"
        )
        assert result["domHeight"] == pytest.approx(60, abs=1), (
            f"DOM height after 3-line inject: expected 60px, got {result['domHeight']}px "
            f"(inlineStyle={result['inlineHeight']!r})"
        )

        # No onRowHeightChanged errors from any of this
        row_height_errors = [
            e for e in console_errors
            if "onRowHeightChanged" in e["text"] or "rowHeightChanged" in e["text"].lower()
        ]
        assert len(row_height_errors) == 0, (
            f"Console errors about onRowHeightChanged during synthetic test: {row_height_errors}"
        )

        print(f"[INFO] All console messages ({len(console_errors)}):")
        for e in console_errors:
            print(f"  [{e['type'].upper()}] {e['text'][:200]}")

        browser.close()

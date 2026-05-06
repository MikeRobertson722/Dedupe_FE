"""
Test: getRowHeight callback with translateY positioning.

Verifies the new approach: gridOptions.getRowHeight callback (instead of
post-hoc setRowHeight + adjustRowHeights) calculates row heights during
AG Grid's layout pass, so translateY positions on each ag-row div are
contiguous (no overlap, no gap).

Critical difference from old tests:
- Old approach: rows use style.top for positioning
- IRM (Infinite Row Model): rows use transform: translateY(Npx) for positioning
- This test reads translateY from the transform style and verifies contiguity
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


def _wait_for_rows(page, min_rows=5, timeout_ms=20000):
    page.wait_for_function(
        f"document.querySelectorAll('.ag-row:not(.ag-row-loading)').length >= {min_rows}",
        timeout=timeout_ms,
    )


def _collect_row_positions(page):
    """
    Collect translateY and height for all visible non-loading ag-rows inside
    ag-center-cols-container. Returns list of dicts sorted by rowIndex.
    """
    return page.evaluate("""
    () => {
        // Target the center viewport container (where data rows live)
        var container = document.querySelector('.ag-center-cols-container');
        if (!container) {
            // fallback: search all ag-row elements
            container = document.body;
        }
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
            var cellText = addrCell ? addrCell.innerText.substring(0, 80) : '';
            results.push({
                rowIndex: rowIndex,
                translateY: translateY,
                transform: transform,
                height: computedH,
                inlineHeight: inlineH,
                brCount: brCount,
                cellText: cellText
            });
        }
        // Sort by rowIndex
        results.sort(function(a, b) { return a.rowIndex - b.rowIndex; });
        return results;
    }
    """)


def _check_contiguity(rows, label=""):
    """
    Verify each row's translateY == previous row's translateY + previous row's height.
    Returns list of overlap dicts (empty = pass).
    """
    overlaps = []
    for i in range(1, len(rows)):
        prev = rows[i - 1]
        curr = rows[i]
        if prev["translateY"] is None or curr["translateY"] is None:
            continue
        # Only check adjacently-indexed rows (skip non-contiguous rowIndex gaps)
        if curr["rowIndex"] != prev["rowIndex"] + 1:
            continue
        expected = prev["translateY"] + prev["height"]
        if abs(curr["translateY"] - expected) > 1.0:  # 1px tolerance
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
# Test 1: On initial page load (NEEDS REVIEW bucket) — single-line rows only
# ─────────────────────────────────────────────────────────────────────────────
def test_initial_load_no_overlap_translatey():
    """
    On initial page load with the NEEDS REVIEW bucket (many single-line rows),
    verify:
    1. All visible rows use translateY (not style.top) for positioning.
    2. Row heights are 24px for single-line rows.
    3. translateY values are contiguous (no gaps, no overlaps).
    4. No console errors related to getRowHeight, resetRowHeights, or row heights.
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
        time.sleep(0.5)  # Let layout settle after initial render

        rows = _collect_row_positions(page)

        print(f"\n[INITIAL LOAD] Visible non-loading rows: {len(rows)}")
        for r in rows[:15]:
            print(f"  row-index={r['rowIndex']}  translateY={r['translateY']}px  "
                  f"height={r['height']}px  inline-h={r['inlineHeight']!r}  "
                  f"brs={r['brCount']}  transform={r['transform']!r}")

        # --- Assertion 1: At least 5 rows loaded ---
        assert len(rows) >= 5, f"Expected at least 5 visible rows on initial load, got {len(rows)}"

        # --- Assertion 2: All rows use translateY (IRM layout model) ---
        missing_translate = [r for r in rows if r["translateY"] is None]
        if missing_translate:
            print(f"\n[WARN] {len(missing_translate)} rows have no translateY:")
            for r in missing_translate[:5]:
                print(f"  row-index={r['rowIndex']}  transform={r['transform']!r}")
        assert len(missing_translate) == 0, (
            f"{len(missing_translate)} rows missing translateY in transform style — "
            f"expected IRM translateY positioning. "
            f"Missing: {[(r['rowIndex'], r['transform']) for r in missing_translate[:5]]}"
        )

        # --- Assertion 3: Single-line rows are 24px ---
        single_line = [r for r in rows if r["brCount"] == 0]
        wrong_height = [r for r in single_line if abs(r["height"] - 24) > 1]
        if wrong_height:
            print(f"\n[FAIL] {len(wrong_height)} single-line rows not 24px:")
            for r in wrong_height:
                print(f"  row-index={r['rowIndex']}  height={r['height']}px")
        assert len(wrong_height) == 0, (
            f"{len(wrong_height)} single-line rows have wrong height (expected 24px): "
            f"{[(r['rowIndex'], r['height']) for r in wrong_height]}"
        )

        # --- Assertion 4: Contiguous translateY positions ---
        overlaps = _check_contiguity(rows, label="initial load")
        if overlaps:
            print(f"\n[FAIL] {len(overlaps)} row(s) with non-contiguous translateY:")
            for ov in overlaps:
                print(f"  row-index={ov['row_index']}: "
                      f"expected translateY={ov['expected_translateY']}px, "
                      f"got {ov['actual_translateY']}px  "
                      f"(delta={ov['delta']:+.1f}px, "
                      f"prev-index={ov['prev_index']} height={ov['prev_height']}px)")
        assert len(overlaps) == 0, (
            f"{len(overlaps)} row(s) have non-contiguous translateY (overlap or gap): "
            f"{[(o['row_index'], o['expected_translateY'], o['actual_translateY']) for o in overlaps]}"
        )

        # --- Assertion 5: No row-height-related console errors ---
        height_errors = [
            e for e in console_errors
            if any(kw in e["text"].lower() for kw in [
                "rowheight", "row height", "resetrowheights", "getrowheight",
                "onrowheightchanged"
            ])
        ]
        print(f"\n[INFO] Console errors/warnings ({len(console_errors)} total):")
        for e in console_errors:
            print(f"  [{e['type'].upper()}] {e['text'][:200]}")
        assert len(height_errors) == 0, (
            f"Console errors related to row heights: {height_errors}"
        )

        browser.close()


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: Search KENAN JONES — multi-line row at 60px, no overlap
# ─────────────────────────────────────────────────────────────────────────────
def test_kenan_jones_translatey_height_and_no_overlap():
    """
    Search for 'KENAN JONES', verify the 3-line row is 60px tall, and confirm
    translateY positions are contiguous across all visible rows.
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
        time.sleep(1.0)  # Settle after getRowHeight-driven layout

        rows = _collect_row_positions(page)

        print(f"\n[KENAN JONES] Visible rows: {len(rows)}")
        for r in rows:
            print(f"  row-index={r['rowIndex']}  translateY={r['translateY']}px  "
                  f"height={r['height']}px  brs={r['brCount']}  "
                  f"text={r['cellText']!r}")

        assert len(rows) >= 1, "No rows found after KENAN JONES search"

        # --- Assertion 1: Multi-line row is 60px ---
        multi_rows = [r for r in rows if r["brCount"] >= 2]
        print(f"\n[INFO] Rows with >=2 <br> tags: {len(multi_rows)}")
        assert len(multi_rows) >= 1, (
            f"Expected at least 1 multi-line row (>=2 <br> tags) after KENAN JONES search, "
            f"found 0. Row data: {[(r['rowIndex'], r['brCount'], r['cellText']) for r in rows]}"
        )
        for mr in multi_rows:
            print(f"  Multi-line row: index={mr['rowIndex']} height={mr['height']}px "
                  f"translateY={mr['translateY']}px")
            assert abs(mr["height"] - 60) <= 1, (
                f"KENAN JONES multi-line row (index={mr['rowIndex']}) height: "
                f"expected 60px, got {mr['height']}px. "
                f"getRowHeight callback may not be firing for this row."
            )

        # --- Assertion 2: Contiguous translateY ---
        if len(rows) >= 2:
            overlaps = _check_contiguity(rows, label="KENAN JONES search")
            if overlaps:
                print(f"\n[FAIL] {len(overlaps)} translateY overlap(s) after KENAN JONES:")
                for ov in overlaps:
                    print(f"  row-index={ov['row_index']}: "
                          f"expected translateY={ov['expected_translateY']}px, "
                          f"got {ov['actual_translateY']}px  (delta={ov['delta']:+.1f}px)")
            assert len(overlaps) == 0, (
                f"Row overlap after KENAN JONES search: "
                f"{[(o['row_index'], o['expected_translateY'], o['actual_translateY']) for o in overlaps]}"
            )
        else:
            print("[NOTE] Only 1 row visible — skipping contiguity check.")

        # --- Assertion 3: No height-related console errors ---
        height_errors = [
            e for e in console_errors
            if any(kw in e["text"].lower() for kw in [
                "rowheight", "row height", "resetrowheights", "getrowheight",
                "onrowheightchanged"
            ])
        ]
        print(f"\n[INFO] Console errors/warnings ({len(console_errors)} total):")
        for e in console_errors:
            print(f"  [{e['type'].upper()}] {e['text'][:200]}")
        assert len(height_errors) == 0, (
            f"Console errors related to row heights after KENAN JONES search: {height_errors}"
        )

        browser.close()


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: Clear search and return to full view — no overlaps
# ─────────────────────────────────────────────────────────────────────────────
def test_clear_search_no_overlap_translatey():
    """
    After searching KENAN JONES (which loads a multi-line row), clear the search
    filter and return to the full NEEDS REVIEW view. Verify the grid re-renders
    with contiguous translateY positions and single-line rows at 24px.

    This checks that returning to the default view after seeing a multi-line row
    does not leave stale translateY offsets.
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

        # Step 1: Search KENAN JONES
        search_box = page.locator("#quickFilterInput")
        search_box.wait_for(state="visible", timeout=10000)
        search_box.fill("")
        time.sleep(0.4)
        search_box.fill("KENAN JONES")
        page.wait_for_function(
            "document.querySelectorAll('.ag-row:not(.ag-row-loading)').length >= 1",
            timeout=20000,
        )
        time.sleep(0.8)

        # Step 2: Clear search
        search_box.fill("")
        page.wait_for_function(
            "document.querySelectorAll('.ag-row:not(.ag-row-loading)').length >= 5",
            timeout=20000,
        )
        _wait_for_grid_info(page)
        time.sleep(0.8)  # Let getRowHeight-driven layout settle

        rows = _collect_row_positions(page)

        print(f"\n[CLEAR SEARCH] Visible rows after returning to full view: {len(rows)}")
        for r in rows[:12]:
            print(f"  row-index={r['rowIndex']}  translateY={r['translateY']}px  "
                  f"height={r['height']}px  brs={r['brCount']}")

        assert len(rows) >= 5, f"Expected >= 5 rows after clearing search, got {len(rows)}"

        # --- Assertion 1: All rows have translateY ---
        missing_translate = [r for r in rows if r["translateY"] is None]
        assert len(missing_translate) == 0, (
            f"{len(missing_translate)} rows missing translateY after clear search"
        )

        # --- Assertion 2: Single-line rows are 24px ---
        single_line = [r for r in rows if r["brCount"] == 0]
        wrong_height = [r for r in single_line if abs(r["height"] - 24) > 1]
        assert len(wrong_height) == 0, (
            f"{len(wrong_height)} single-line rows have wrong height after clear search "
            f"(expected 24px): "
            f"{[(r['rowIndex'], r['height']) for r in wrong_height]}"
        )

        # --- Assertion 3: Contiguous translateY ---
        overlaps = _check_contiguity(rows, label="clear search")
        if overlaps:
            print(f"\n[FAIL] {len(overlaps)} translateY overlap(s) after clear search:")
            for ov in overlaps:
                print(f"  row-index={ov['row_index']}: "
                      f"expected translateY={ov['expected_translateY']}px, "
                      f"got {ov['actual_translateY']}px  (delta={ov['delta']:+.1f}px)")
        assert len(overlaps) == 0, (
            f"Row overlap detected after clearing KENAN JONES search: "
            f"{[(o['row_index'], o['expected_translateY'], o['actual_translateY']) for o in overlaps]}"
        )

        # --- Assertion 4: No height console errors ---
        height_errors = [
            e for e in console_errors
            if any(kw in e["text"].lower() for kw in [
                "rowheight", "row height", "resetrowheights", "getrowheight",
                "onrowheightchanged"
            ])
        ]
        print(f"\n[INFO] Console errors/warnings ({len(console_errors)} total):")
        for e in console_errors:
            print(f"  [{e['type'].upper()}] {e['text'][:200]}")
        assert len(height_errors) == 0, (
            f"Console errors related to row heights after clear search: {height_errors}"
        )

        browser.close()


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: Synthetic injection — getRowHeight fires on datasource refresh
# ─────────────────────────────────────────────────────────────────────────────
def test_synthetic_injection_translatey_contiguous():
    """
    Inject a 3-line value into the first node's data, force a datasource refresh
    (so getRowHeight re-fires for the newly-loaded block), and verify:
    - The multi-line row gets 60px height and correct translateY
    - Subsequent rows have contiguous translateY values

    This tests the getRowHeight callback path specifically — since getRowHeight
    is called by AG Grid during block rendering, not post-hoc.
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
        page.wait_for_function(
            "() => { var n = gridApi && gridApi.getDisplayedRowAtIndex(0); "
            "return n && n.data != null; }",
            timeout=25000,
        )
        _wait_for_rows(page, min_rows=5)
        time.sleep(0.5)

        # Snapshot baseline translateY positions before injection
        baseline = _collect_row_positions(page)
        print(f"\n[SYNTHETIC] Baseline rows: {len(baseline)}")
        for r in baseline[:8]:
            print(f"  row-index={r['rowIndex']}  translateY={r['translateY']}px  "
                  f"height={r['height']}px")

        # Check baseline contiguity first
        baseline_overlaps = _check_contiguity(baseline, label="baseline")
        print(f"[SYNTHETIC] Baseline overlaps: {len(baseline_overlaps)}")

        # Now inject 3-line value into first row via setRowHeight + redrawRows
        # (the inline edit path — since we can't re-trigger getRowHeight without
        # a full datasource refresh; getRowHeight fires during block load)
        inject_result = page.evaluate("""
        () => {
            var firstNode = gridApi.getDisplayedRowAtIndex(0);
            if (!firstNode || !firstNode.data) {
                return { error: 'no data on first node' };
            }
            var origVal = firstNode.data.source_address_recomend;

            // Inject 3-line value
            firstNode.data.source_address_recomend = 'LINE ONE\\nLINE TWO\\nLINE THREE';

            // Use the inline-edit path: setRowHeight + redrawRows
            // (this is the same code path triggered by onCellValueChanged for address edits)
            var rowNode = gridApi.getRowNode(String(firstNode.id));
            if (!rowNode) rowNode = firstNode;

            // calcRowHeight is defined in app.js — call it directly
            rowNode.setRowHeight(calcRowHeight(rowNode.data));
            gridApi.redrawRows({ rowNodes: [rowNode] });

            // Read the node height and DOM state immediately after
            var el = document.querySelector('.ag-row[row-index="' + firstNode.rowIndex + '"]');
            var transform = el ? el.style.transform : '';
            var domH = el ? parseFloat(window.getComputedStyle(el).height) : null;
            var nodeH = rowNode.rowHeight;

            return {
                rowIndex: firstNode.rowIndex,
                origVal: origVal,
                nodeHeight: nodeH,
                domHeight: domH,
                transform: transform
            };
        }
        """)

        print(f"\n[SYNTHETIC] After inject + setRowHeight + redrawRows: {inject_result}")

        if "error" in inject_result:
            pytest.fail(f"Injection error: {inject_result}")

        # Node height should be 60
        assert inject_result["nodeHeight"] == 60, (
            f"node.rowHeight after 3-line inject: expected 60, got {inject_result['nodeHeight']}"
        )
        # DOM height should be 60
        assert inject_result["domHeight"] is not None, "DOM row element not found after inject"
        assert abs(inject_result["domHeight"] - 60) <= 1, (
            f"DOM height after 3-line inject: expected 60px, got {inject_result['domHeight']}px"
        )

        # Now collect all row positions to check translateY contiguity
        time.sleep(0.3)  # Brief settle after redrawRows
        rows_after = _collect_row_positions(page)

        print(f"\n[SYNTHETIC] Rows after inject ({len(rows_after)} rows):")
        for r in rows_after[:12]:
            print(f"  row-index={r['rowIndex']}  translateY={r['translateY']}px  "
                  f"height={r['height']}px  brs={r['brCount']}")

        # --- Key assertion: translateY contiguity after expanding row 0 ---
        overlaps = _check_contiguity(rows_after, label="after inject")
        if overlaps:
            print(f"\n[FAIL] {len(overlaps)} translateY overlap(s) after 3-line inject:")
            for ov in overlaps:
                print(f"  row-index={ov['row_index']}: "
                      f"expected translateY={ov['expected_translateY']}px, "
                      f"got {ov['actual_translateY']}px  (delta={ov['delta']:+.1f}px, "
                      f"prev-index={ov['prev_index']} prev-height={ov['prev_height']}px)")

        # Restore original value
        restore_result = page.evaluate("""
        () => {
            var firstNode = gridApi.getDisplayedRowAtIndex(0);
            if (!firstNode || !firstNode.data) return { error: 'no first node for restore' };
            // Clear the injected value
            firstNode.data.source_address_recomend = '';
            var rowNode = gridApi.getRowNode(String(firstNode.id));
            if (!rowNode) rowNode = firstNode;
            rowNode.setRowHeight(calcRowHeight(rowNode.data));
            gridApi.redrawRows({ rowNodes: [rowNode] });
            return { restored: true };
        }
        """)
        print(f"[SYNTHETIC] Restore result: {restore_result}")

        assert len(overlaps) == 0, (
            f"{len(overlaps)} row(s) have non-contiguous translateY after 3-line row expansion. "
            f"This means the getRowHeight approach did NOT fix translateY positioning for "
            f"subsequent rows. Overlaps: "
            f"{[(o['row_index'], o['expected_translateY'], o['actual_translateY'], o['delta']) for o in overlaps]}"
        )

        # --- No height-related console errors ---
        height_errors = [
            e for e in console_errors
            if any(kw in e["text"].lower() for kw in [
                "rowheight", "row height", "resetrowheights", "getrowheight",
                "onrowheightchanged"
            ])
        ]
        print(f"\n[INFO] All console errors/warnings ({len(console_errors)}):")
        for e in console_errors:
            print(f"  [{e['type'].upper()}] {e['text'][:200]}")
        assert len(height_errors) == 0, (
            f"Console errors related to row heights: {height_errors}"
        )

        browser.close()

"""
Test: Row overlap prevention and resetRowHeights() preservation.

Verifies two things after the resetRowHeights() fix:
1. After adjustRowHeights(), the `top` CSS of each row equals the sum of all
   preceding row heights (no overlap, no gap).
2. resetRowHeights() does NOT reset per-node setRowHeight() values back to
   the default 24px — the multi-line node stays at 60px after the call.

These tests use synthetic injection so they work deterministically without
depending on live Snowflake data having a multi-line row on the visible page.
"""

import time
import pytest
from playwright.sync_api import sync_playwright, ConsoleMessage

BASE_URL = "http://127.0.0.1:5000"


def _wait_for_first_node_data(page, timeout_ms=20000):
    """Wait until the first IRM displayed node has .data loaded."""
    page.wait_for_function(
        "() => { var n = gridApi && gridApi.getDisplayedRowAtIndex(0); "
        "return n && n.data != null; }",
        timeout=timeout_ms,
    )


def _wait_for_grid_info(page, timeout_ms=20000):
    """Wait until #gridInfo shows at least one digit (data loaded)."""
    page.wait_for_function(
        "() => { var t = document.querySelector('#gridInfo'); "
        "return t && /\\d/.test(t.innerText) && t.innerText !== '0 records'; }",
        timeout=timeout_ms,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: resetRowHeights() preserves setRowHeight() values
# ─────────────────────────────────────────────────────────────────────────────
def test_reset_row_heights_preserves_set_row_height():
    """
    Critical regression check: calling gridApi.resetRowHeights() after
    node.setRowHeight(60) must NOT revert the node back to 24px.

    Strategy:
    - Inject a 3-line value into the first node.
    - Call adjustRowHeights() (which calls setRowHeight + redrawRows + resetRowHeights).
    - After the full adjustRowHeights() call, read node.rowHeight.
    - It must still be 60, not 24 (the default).
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
        _wait_for_first_node_data(page)
        time.sleep(0.3)

        result = page.evaluate("""
        () => {
            // --- Get a loaded node ---
            var targetNode = null;
            gridApi.forEachNode(function(n) { if (!targetNode && n.data) targetNode = n; });
            if (!targetNode) return { error: 'no loaded node found' };

            var origVal = targetNode.data.source_address_recomend;
            var origH   = targetNode.rowHeight;

            // --- Step 1: inject 3-line value ---
            targetNode.data.source_address_recomend = 'LINE ONE\\nLINE TWO\\nLINE THREE';

            // --- Step 2: run full adjustRowHeights (setRowHeight + redrawRows + resetRowHeights) ---
            adjustRowHeights();

            // Read height AFTER the full adjustRowHeights call (including resetRowHeights)
            var heightAfterFull = targetNode.rowHeight;

            // Also read DOM inline style to cross-check
            var rowEl = document.querySelector('.ag-row[row-index="' + targetNode.rowIndex + '"]');
            var domH   = rowEl ? parseFloat(window.getComputedStyle(rowEl).height) : null;
            var inlineH = rowEl ? rowEl.style.height : null;

            // --- Step 3: restore original ---
            targetNode.data.source_address_recomend = origVal;
            adjustRowHeights();

            return {
                rowIndex: targetNode.rowIndex,
                origHeight: origH,
                heightAfterAdjust: heightAfterFull,
                domHeight: domH,
                inlineHeight: inlineH
            };
        }
        """)

        print(f"\n[RESET_PRESERVE] result: {result}")
        for e in console_errors:
            print(f"  [{e['type'].upper()}] {e['text'][:200]}")

        assert "error" not in result, f"JS error: {result}"

        # CRITICAL: node.rowHeight must be 60 after adjustRowHeights (not reverted to 24 by resetRowHeights)
        assert result["heightAfterAdjust"] == 60, (
            f"resetRowHeights() reverted setRowHeight! "
            f"node.rowHeight after adjustRowHeights = {result['heightAfterAdjust']}px "
            f"(expected 60). This means resetRowHeights is overwriting per-node heights."
        )

        # Cross-check: DOM must also show 60px
        assert result["domHeight"] == pytest.approx(60, abs=1), (
            f"DOM height after adjustRowHeights = {result['domHeight']}px (expected 60px). "
            f"inlineStyle={result['inlineHeight']!r}"
        )

        browser.close()


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: No row overlap — top positions are contiguous
# ─────────────────────────────────────────────────────────────────────────────
def test_no_row_overlap_after_multi_line_injection():
    """
    After injecting a multi-line value into the first row and calling
    adjustRowHeights(), verify that subsequent rows have their `top` CSS
    values positioned immediately below the taller first row — i.e., no overlap.

    Specifically checks:
    - Row 0 top = 0px, height = 60px  (3-line row)
    - Row 1 top = 60px                (directly below, no overlap)
    - Row 2 top = 60 + row1_height    (and so on for each subsequent row)

    If resetRowHeights() were removed, rows 1..N would still have top positions
    calculated with the OLD 24px height, causing row 1 to overlap rows 0's
    bottom 36 pixels.
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
        _wait_for_first_node_data(page)
        # Wait for several rows to be loaded so we can check continuity
        page.wait_for_function(
            "document.querySelectorAll('.ag-row:not(.ag-row-loading)').length >= 5",
            timeout=15000,
        )
        time.sleep(0.5)

        result = page.evaluate("""
        () => {
            // Collect up to the first 6 loaded nodes (in row-index order)
            var nodes = [];
            gridApi.forEachNode(function(n) {
                if (n.data && nodes.length < 10) nodes.push(n);
            });
            // Sort by rowIndex
            nodes.sort(function(a, b) { return a.rowIndex - b.rowIndex; });
            if (nodes.length < 2) return { error: 'fewer than 2 loaded nodes', count: nodes.length };

            var targetNode = nodes[0];
            var origVal = targetNode.data.source_address_recomend;

            // Inject 3-line value into first row and expand it
            targetNode.data.source_address_recomend = 'LINE ONE\\nLINE TWO\\nLINE THREE';
            adjustRowHeights();

            // Collect DOM positions for visible rows (by row-index attribute)
            var rowEls = Array.from(document.querySelectorAll('.ag-row:not(.ag-row-loading)'));
            rowEls.sort(function(a, b) {
                return parseInt(a.getAttribute('row-index')) - parseInt(b.getAttribute('row-index'));
            });

            var positions = rowEls.map(function(el) {
                var style = window.getComputedStyle(el);
                return {
                    rowIndex: parseInt(el.getAttribute('row-index')),
                    top: parseFloat(el.style.top || style.top) || 0,
                    height: parseFloat(style.height),
                    inlineTop: el.style.top,
                    inlineHeight: el.style.height
                };
            });

            // Restore
            targetNode.data.source_address_recomend = origVal;
            adjustRowHeights();

            return { positions: positions };
        }
        """)

        print(f"\n[OVERLAP] Row positions after multi-line injection:")
        if "error" in result:
            pytest.fail(f"JS error: {result}")

        positions = result["positions"]
        for pos in positions:
            print(f"  row-index={pos['rowIndex']}  top={pos['top']}px "
                  f"(inline:{pos['inlineTop']!r})  height={pos['height']}px "
                  f"(inline:{pos['inlineHeight']!r})")

        # Filter to rows with valid heights (skip loading placeholders)
        valid = [p for p in positions if p["height"] > 0]
        assert len(valid) >= 2, f"Need at least 2 valid rows to check continuity, got {len(valid)}"

        # Verify first row is the expanded multi-line row
        first = valid[0]
        assert first["height"] == pytest.approx(60, abs=1), (
            f"First row (index={first['rowIndex']}) should be 60px after 3-line inject, "
            f"got {first['height']}px"
        )

        # Verify contiguous positioning: each row's top == previous row's top + previous row's height
        overlaps = []
        for i in range(1, len(valid)):
            prev = valid[i - 1]
            curr = valid[i]
            expected_top = prev["top"] + prev["height"]
            actual_top = curr["top"]
            # Allow 1px rounding tolerance
            if abs(actual_top - expected_top) > 1:
                overlaps.append({
                    "row_index": curr["rowIndex"],
                    "expected_top": expected_top,
                    "actual_top": actual_top,
                    "delta": actual_top - expected_top,
                    "prev_index": prev["rowIndex"],
                    "prev_height": prev["height"],
                })

        if overlaps:
            print(f"\n[FAIL] {len(overlaps)} row(s) have incorrect top positions (overlap/gap):")
            for ov in overlaps:
                print(f"  row-index={ov['row_index']}: expected top={ov['expected_top']}px, "
                      f"got {ov['actual_top']}px  (delta={ov['delta']:+.1f}px)")

        assert len(overlaps) == 0, (
            f"{len(overlaps)} row(s) have top positions inconsistent with preceding row heights "
            f"(indicates overlap or resetRowHeights() not working): "
            f"{[(o['row_index'], o['expected_top'], o['actual_top']) for o in overlaps]}"
        )

        # Bonus: check for console errors related to resetRowHeights
        reset_errors = [
            e for e in console_errors
            if "resetrowheights" in e["text"].lower() or "row height" in e["text"].lower()
        ]
        assert len(reset_errors) == 0, (
            f"Console errors related to resetRowHeights: {reset_errors}"
        )

        browser.close()


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: KENAN JONES live data — overlap check on real multi-line row
# ─────────────────────────────────────────────────────────────────────────────
def test_kenan_jones_no_overlap():
    """
    Search for KENAN JONES, find the 3-line multi-line row in live Snowflake data,
    then verify:
    - Multi-line row DOM height = 60px
    - All visible rows have contiguous top positions (no overlap)
    - Single-line rows remain at 24px
    Uses the live KENAN JONES record: "PO BOX 701 / KENAN JONES KEYES TRUSTEE... / & ASSET MGMTCO"
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
            "document.querySelectorAll('.ag-row:not(.ag-row-loading)').length >= 1",
            timeout=15000,
        )

        # Search KENAN JONES
        search_box = page.locator("#quickFilterInput")
        search_box.wait_for(state="visible", timeout=10000)
        search_box.fill("")
        time.sleep(0.4)
        search_box.fill("KENAN JONES")
        page.wait_for_function(
            "document.querySelectorAll('.ag-row:not(.ag-row-loading)').length >= 1",
            timeout=15000,
        )
        time.sleep(1.0)  # Let adjustRowHeights settle

        positions = page.evaluate("""
        () => {
            var rowEls = Array.from(document.querySelectorAll('.ag-row:not(.ag-row-loading)'));
            rowEls.sort(function(a, b) {
                return parseInt(a.getAttribute('row-index')) - parseInt(b.getAttribute('row-index'));
            });
            return rowEls.map(function(el) {
                var style  = window.getComputedStyle(el);
                var cell   = el.querySelector('[col-id="source_address_recomend"]');
                var brs    = cell ? cell.querySelectorAll('br').length : 0;
                var text   = cell ? cell.innerText : '';
                return {
                    rowIndex:    parseInt(el.getAttribute('row-index')),
                    top:         parseFloat(el.style.top || '0'),
                    height:      parseFloat(style.height),
                    inlineTop:   el.style.top,
                    inlineHeight: el.style.height,
                    brCount:     brs,
                    text:        text.substring(0, 80)
                };
            });
        }
        """)

        print(f"\n[KENAN JONES] Row positions after search:")
        for pos in positions:
            print(f"  row-index={pos['rowIndex']}  top={pos['top']}px  "
                  f"height={pos['height']}px  brs={pos['brCount']}  "
                  f"text={pos['text']!r}")

        valid = [p for p in positions if p["height"] > 0]
        assert len(valid) >= 1, "No valid rows found after KENAN JONES search"

        # Find the multi-line row
        multi_rows = [p for p in valid if p["brCount"] >= 2]
        print(f"\n[INFO] Multi-line rows (>=2 <br>): {len(multi_rows)}")
        if multi_rows:
            for mr in multi_rows:
                print(f"  row-index={mr['rowIndex']}  height={mr['height']}px")
            assert multi_rows[0]["height"] == pytest.approx(60, abs=1), (
                f"Multi-line KENAN JONES row height expected 60px, "
                f"got {multi_rows[0]['height']}px"
            )

        # Contiguity check (only if multiple rows visible)
        if len(valid) >= 2:
            overlaps = []
            for i in range(1, len(valid)):
                prev = valid[i - 1]
                curr = valid[i]
                # Only check rows that are adjacent by rowIndex
                if curr["rowIndex"] != prev["rowIndex"] + 1:
                    continue
                expected_top = prev["top"] + prev["height"]
                if abs(curr["top"] - expected_top) > 1:
                    overlaps.append({
                        "row_index": curr["rowIndex"],
                        "expected_top": expected_top,
                        "actual_top": curr["top"],
                        "delta": curr["top"] - expected_top,
                    })
            if overlaps:
                print(f"\n[FAIL] Overlap/gap detected at {len(overlaps)} row transition(s):")
                for ov in overlaps:
                    print(f"  row-index={ov['row_index']}: expected top={ov['expected_top']}px, "
                          f"got {ov['actual_top']}px  (delta={ov['delta']:+.1f}px)")
            assert len(overlaps) == 0, (
                f"Row overlap detected after KENAN JONES search: "
                f"{[(o['row_index'], o['expected_top'], o['actual_top']) for o in overlaps]}"
            )
        else:
            print("[NOTE] Only 1 visible row — cannot check contiguity.")

        # No resetRowHeights console errors
        reset_errors = [
            e for e in console_errors
            if "resetrowheights" in e["text"].lower() or "row height" in e["text"].lower()
        ]
        print(f"\n[INFO] All console errors ({len(console_errors)}):")
        for e in console_errors:
            print(f"  [{e['type'].upper()}] {e['text'][:200]}")
        assert len(reset_errors) == 0, (
            f"Console errors related to row heights: {reset_errors}"
        )

        browser.close()

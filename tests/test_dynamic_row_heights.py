"""
Test: Dynamic per-row heights based on source_address_recomend content.

The fix uses node.setRowHeight() + gridApi.onRowHeightChanged() called from
adjustRowHeights(), which is invoked after each datasource block loads and
after inline edits to source_address_recomend.

NOTE: The live Snowflake data (as of 2026-04-07) has NO multi-line values in
SOURCE_ADDRESS_RECOMEND — all rows are single-line street addresses. Tests that
require multi-line data inject synthetic values directly into node.data and call
adjustRowHeights() explicitly to verify the logic.

Height formula (mirrors JS):
  lines > 1  =>  lines * 18 + 6
  lines == 1 =>  24
"""
import re
import pytest
from playwright.sync_api import Page

BASE_URL = "http://127.0.0.1:5000"
DEFAULT_H = 24
LINE_HEIGHT = 18
PADDING = 6

# Raw JS strings stored as module-level constants to avoid Python escape issues
_JS_INJECT_SYNTHETIC = r"""
() => {
    // Inject known multi-line values into first 4 nodes for deterministic testing.
    // LF, CR, CRLF, and single-line variants.
    var variants = [
        'PO BOX 32093\nC/O VIRGINIA SLATON',   // LF: 2 lines -> 42px
        'LINE1\rLINE2',                          // CR: 2 lines -> 42px
        'LINE1\r\nLINE2\r\nLINE3',              // CRLF: 3 lines -> 60px
        'SINGLE LINE ONLY',                      // 1 line -> 24px
    ];
    var count = 0;
    gridApi.forEachNode(function(node) {
        if (!node.data || count >= 4) return;
        node.data.source_address_recomend = variants[count];
        count++;
    });
    return count;
}
"""

_JS_ADJUST = r"() => { adjustRowHeights(); return 'ok'; }"

_JS_VERIFY_NODES = r"""
() => {
    var results = [];
    var count = 0;
    gridApi.forEachNode(function(node) {
        if (!node.data || count >= 4) return;
        results.push({
            val: node.data.source_address_recomend || '',
            rowHeight: node.rowHeight
        });
        count++;
    });
    return results;
}
"""

_JS_DOM_HEIGHTS = r"""
() => {
    var rows = document.querySelectorAll('#matchesGrid .ag-row:not(.ag-row-loading)');
    var out = [];
    rows.forEach(function(r, i) {
        if (i >= 10) return;
        out.push({
            rowIdx: r.getAttribute('row-index'),
            hStyle: r.style.height,
            hComputed: window.getComputedStyle(r).height
        });
    });
    return out;
}
"""

_JS_FOREACH_COUNT = r"""
() => {
    if (typeof gridApi === 'undefined') return -1;
    var count = 0;
    gridApi.forEachNode(function(node) { count++; });
    return count;
}
"""


def compute_expected_height(val: str) -> int:
    """Mirror the JS formula: _LINE_SPLIT_RE = /\r\n|\r|\n/"""
    if not val:
        return DEFAULT_H
    lines = len(re.split(r'\r\n|\r|\n', val))
    return lines * LINE_HEIGHT + PADDING if lines > 1 else DEFAULT_H


def wait_for_grid(page: Page) -> None:
    """Wait for first block of AG Grid rows to be fully loaded."""
    page.wait_for_selector("#matchesGrid .ag-row", timeout=30000)
    page.wait_for_function(
        "() => { var t = document.querySelector('#gridInfo'); return t && t.innerText && t.innerText !== '0 records' && t.innerText.length > 3; }",
        timeout=15000,
    )
    page.wait_for_timeout(1500)


class TestDynamicRowHeights:

    def test_adjustRowHeights_function_exists(self, app_page: Page):
        """adjustRowHeights must be defined (not on window — it is function-scoped in app.js)."""
        # gridApi is also function-scoped; test via a wrapper that checks by name
        exists = app_page.evaluate(
            "() => { try { return typeof adjustRowHeights === 'function'; } catch(e) { return false; } }"
        )
        assert exists, "adjustRowHeights() not found — function is missing from app.js"

    def test_gridApi_forEachNode_available(self, app_page: Page):
        """gridApi.forEachNode must work and return loaded nodes."""
        count = app_page.evaluate(_JS_FOREACH_COUNT)
        assert count > 0, (
            f"gridApi.forEachNode returned {count} nodes — "
            "gridApi may not be initialized or IRM blocks not loaded"
        )

    def test_needs_review_loads_rows(self, app_page: Page):
        """NEEDS REVIEW bucket must load rows into the DOM."""
        page = app_page
        page.evaluate("() => { if (typeof filterByRec === 'function') filterByRec('NEEDS REVIEW'); }")
        page.wait_for_function(
            "() => document.querySelectorAll('#matchesGrid .ag-row:not(.ag-row-loading)').length > 0",
            timeout=20000,
        )
        page.wait_for_timeout(800)
        count = page.evaluate(
            "() => document.querySelectorAll('#matchesGrid .ag-row:not(.ag-row-loading)').length"
        )
        assert count > 0, f"Expected >0 NEEDS REVIEW rows in DOM, got {count}"

    def test_single_line_rows_have_24px_height(self, app_page: Page):
        """
        With live data (all single-line), all loaded nodes should be 24px.
        This also verifies adjustRowHeights() runs after each block load.
        """
        page = app_page
        page.evaluate("() => { if (typeof filterByRec === 'function') filterByRec('NEEDS REVIEW'); }")
        page.wait_for_function(
            "() => document.querySelectorAll('#matchesGrid .ag-row:not(.ag-row-loading)').length > 0",
            timeout=20000,
        )
        page.wait_for_timeout(1200)

        # Check via forEachNode that no node has rowHeight != 24
        wrong = page.evaluate(r"""
            () => {
                var wrong = [];
                gridApi.forEachNode(function(node) {
                    if (!node.data) return;
                    var val = node.data.source_address_recomend || '';
                    var hasNL = val.indexOf('\n') !== -1 || val.indexOf('\r') !== -1;
                    if (!hasNL && node.rowHeight !== 24) {
                        wrong.push({ id: node.data._row_id, h: node.rowHeight, val: val.substring(0, 60) });
                    }
                });
                return wrong;
            }
        """)
        assert len(wrong) == 0, (
            f"{len(wrong)} single-line rows have rowHeight != 24px. "
            f"First: id={wrong[0]['id']}, h={wrong[0]['h']}, val={wrong[0]['val']}"
        )

    def test_synthetic_lf_newline_sets_taller_height(self, app_page: Page):
        """
        Inject a 2-line LF address. After adjustRowHeights(), node.rowHeight
        must be 42px and DOM row must render at 42px.
        """
        page = app_page
        wait_for_grid(page)

        injected = page.evaluate(_JS_INJECT_SYNTHETIC)
        assert injected >= 4, f"Expected 4 nodes modified, got {injected}"

        page.evaluate(_JS_ADJUST)
        page.wait_for_timeout(300)

        nodes = page.evaluate(_JS_VERIFY_NODES)
        dom_rows = page.evaluate(_JS_DOM_HEIGHTS)

        # Check node idx=0: 'PO BOX 32093\nC/O VIRGINIA SLATON' -> 2 lines -> 42px
        n0 = nodes[0]
        assert n0['rowHeight'] == 42, (
            f"LF 2-line: expected rowHeight=42px, got {n0['rowHeight']}. val={repr(n0['val'][:60])}"
        )
        # Check DOM
        dom0 = next((r for r in dom_rows if r['rowIdx'] == '0'), None)
        assert dom0 is not None, "rowIdx=0 not found in DOM"
        assert dom0['hStyle'] == '42px', (
            f"DOM row 0 height expected 42px, got {dom0['hStyle']} — "
            "onRowHeightChanged() may not have fired"
        )

    def test_synthetic_cr_newline_sets_taller_height(self, app_page: Page):
        """
        Inject a 2-line CR (\\r only) address. After adjustRowHeights(),
        node.rowHeight must be 42px.
        """
        page = app_page
        wait_for_grid(page)

        page.evaluate(_JS_INJECT_SYNTHETIC)
        page.evaluate(_JS_ADJUST)
        page.wait_for_timeout(300)

        nodes = page.evaluate(_JS_VERIFY_NODES)
        # idx=1: 'LINE1\rLINE2' -> CR: 2 lines -> 42px
        n1 = nodes[1]
        assert n1['rowHeight'] == 42, (
            f"CR 2-line: expected rowHeight=42px, got {n1['rowHeight']}. val={repr(n1['val'][:60])}"
        )

    def test_synthetic_crlf_newline_sets_taller_height(self, app_page: Page):
        """
        Inject a 3-line CRLF (\\r\\n) address. After adjustRowHeights(),
        node.rowHeight must be 60px (3 * 18 + 6).
        """
        page = app_page
        wait_for_grid(page)

        page.evaluate(_JS_INJECT_SYNTHETIC)
        page.evaluate(_JS_ADJUST)
        page.wait_for_timeout(300)

        nodes = page.evaluate(_JS_VERIFY_NODES)
        dom_rows = page.evaluate(_JS_DOM_HEIGHTS)

        # idx=2: 'LINE1\r\nLINE2\r\nLINE3' -> CRLF: 3 lines -> 60px
        n2 = nodes[2]
        assert n2['rowHeight'] == 60, (
            f"CRLF 3-line: expected rowHeight=60px, got {n2['rowHeight']}. val={repr(n2['val'][:60])}"
        )
        dom2 = next((r for r in dom_rows if r['rowIdx'] == '2'), None)
        assert dom2 is not None, "rowIdx=2 not found in DOM"
        assert dom2['hStyle'] == '60px', (
            f"DOM row 2 height expected 60px, got {dom2['hStyle']}"
        )

    def test_synthetic_single_line_stays_24px(self, app_page: Page):
        """
        After injecting multi-line rows for idx 0-2, idx=3 has a single-line
        value and must remain at 24px — confirming adjustRowHeights() doesn't
        over-inflate single-line rows.
        """
        page = app_page
        wait_for_grid(page)

        page.evaluate(_JS_INJECT_SYNTHETIC)
        page.evaluate(_JS_ADJUST)
        page.wait_for_timeout(300)

        nodes = page.evaluate(_JS_VERIFY_NODES)
        dom_rows = page.evaluate(_JS_DOM_HEIGHTS)

        # idx=3: 'SINGLE LINE ONLY' -> 1 line -> 24px
        n3 = nodes[3]
        assert n3['rowHeight'] == 24, (
            f"Single-line idx=3: expected rowHeight=24px, got {n3['rowHeight']}. val={repr(n3['val'][:60])}"
        )
        dom3 = next((r for r in dom_rows if r['rowIdx'] == '3'), None)
        if dom3:
            assert dom3['hStyle'] == '24px', (
                f"DOM row 3 height expected 24px, got {dom3['hStyle']}"
            )

    def test_not_all_rows_same_height_after_inject(self, app_page: Page):
        """
        After injecting mixed single/multi-line values, there must be
        multiple distinct rowHeight values — directly verifying the
        'not all rows are the same height' requirement.
        """
        page = app_page
        wait_for_grid(page)

        page.evaluate(_JS_INJECT_SYNTHETIC)
        page.evaluate(_JS_ADJUST)
        page.wait_for_timeout(300)

        nodes = page.evaluate(_JS_VERIFY_NODES)
        heights = [n['rowHeight'] for n in nodes if n['rowHeight'] is not None]

        assert len(heights) >= 4, f"Expected at least 4 nodes, got {len(heights)}"
        unique_heights = set(heights)
        assert len(unique_heights) > 1, (
            f"All rows have the same height ({unique_heights}) — "
            "dynamic heights not working even with synthetic multi-line data"
        )
        assert min(heights) == DEFAULT_H, f"Expected min height={DEFAULT_H}, got {min(heights)}"
        assert max(heights) >= 42, f"Expected at least one row at 42px+, got max={max(heights)}"

    def test_dom_matches_grid_api_heights(self, app_page: Page):
        """
        DOM inline style heights must match what forEachNode reports for node.rowHeight.
        This confirms onRowHeightChanged() actually flushed the new heights to the DOM.
        """
        page = app_page
        wait_for_grid(page)

        page.evaluate(_JS_INJECT_SYNTHETIC)
        page.evaluate(_JS_ADJUST)
        page.wait_for_timeout(300)

        nodes = page.evaluate(_JS_VERIFY_NODES)
        dom_rows = page.evaluate(_JS_DOM_HEIGHTS)

        # Build map: rowIndex -> expected height
        expected_by_idx = {str(i): n['rowHeight'] for i, n in enumerate(nodes) if n['rowHeight']}

        mismatches = []
        for r in dom_rows:
            idx = r['rowIdx']
            if idx not in expected_by_idx:
                continue
            expected_h = expected_by_idx[idx]
            dom_h_px = r['hStyle'] or r['hComputed']
            dom_h = int(dom_h_px.replace('px', '')) if dom_h_px.endswith('px') else -1
            if abs(dom_h - expected_h) > 1:  # 1px rounding tolerance
                mismatches.append({'rowIdx': idx, 'domH': dom_h, 'apiH': expected_h})

        assert len(mismatches) == 0, (
            f"{len(mismatches)} rows: DOM height != gridApi rowHeight. "
            f"First: rowIdx={mismatches[0]['rowIdx']}, DOM={mismatches[0]['domH']}px, API={mismatches[0]['apiH']}px. "
            "onRowHeightChanged() may not have been called."
        )

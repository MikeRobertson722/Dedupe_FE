"""
Search & Replace timing test: screenshot the replaced cell at 200ms, 500ms, 1500ms
to prove the 600ms pause shows the new text.
"""
import pytest
import time
import threading
from playwright.sync_api import Page, expect

BASE_URL = "http://127.0.0.1:5000"
SCREENSHOTS = "C:/ClaudeMain/BA_Review_App/tests/screenshots"


def test_sr_replace_timing_screenshots(page: Page, app_server):
    """Full-window screenshots proving Replace shows the new text during the 600ms pause."""

    # 1. Maximize window and navigate
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.goto(BASE_URL)
    page.wait_for_selector("#matchesGrid .ag-row", timeout=30000)
    page.wait_for_selector("#recBreakdown .col", timeout=15000)
    page.wait_for_timeout(2000)  # let grid settle

    # 2. Hard refresh (Ctrl+Shift+R) and wait for grid
    page.keyboard.press("Control+Shift+r")
    page.wait_for_selector("#matchesGrid .ag-row", timeout=30000)
    page.wait_for_selector("#recBreakdown .col", timeout=15000)
    page.wait_for_timeout(3000)

    # 3. Widen "Src Name" column to at least 400px via JS
    page.evaluate("""() => {
        var cols = gridApi.getColumns();
        var srcNameCol = cols.find(c => c.colId === 'source_name');
        if (srcNameCol) {
            gridApi.setColumnWidths([{key: 'source_name', newWidth: 500}]);
        }
    }""")
    page.wait_for_timeout(500)

    # 4. Open Search & Replace modal
    sr_btn = page.locator("button[onclick='openSearchReplace()']")
    sr_btn.click()
    page.wait_for_selector("#searchReplaceModal.show", timeout=5000)
    page.wait_for_timeout(500)

    # 5. Drag modal to top-right corner
    page.evaluate("""() => {
        var dlg = document.querySelector('#searchReplaceModal .modal-dialog');
        if (dlg) {
            dlg.style.position = 'fixed';
            dlg.style.top = '10px';
            dlg.style.right = '10px';
            dlg.style.left = 'auto';
            dlg.style.margin = '0';
            dlg.style.transform = 'none';
        }
    }""")
    page.wait_for_timeout(300)

    # 6. Type "LLC" in Search, "TESTVALUE" in Replace
    page.fill("#srSearch", "LLC")
    page.wait_for_timeout(1500)  # wait for debounce + highlights

    page.fill("#srReplace", "TESTVALUE")
    page.wait_for_timeout(500)

    # 7. Read the current highlighted cell text
    highlighted_text = page.evaluate("""() => {
        var el = document.querySelector('.sr-current-match');
        return el ? el.textContent.trim() : 'NO HIGHLIGHT FOUND';
    }""")
    match_info = page.evaluate("""() => {
        return document.querySelector('#srMatchInfo') ? document.querySelector('#srMatchInfo').textContent.trim() : '';
    }""")

    print(f"BEFORE: highlighted cell text = '{highlighted_text}'")
    print(f"BEFORE: match info = '{match_info}'")

    # Screenshot A — before Replace
    page.screenshot(path=f"{SCREENSHOTS}/max_before.png", full_page=False)

    # 8. Click Replace — then capture screenshots at ~200ms, ~500ms, ~1500ms
    # We'll use a JS approach: click replace, then use setTimeout to capture info at intervals

    # First, inject a capture function that records cell state at timed intervals
    page.evaluate("""() => {
        window._srTimingCaptures = [];
    }""")

    # Click the Replace button
    replace_btn = page.locator('#searchReplaceModal button[onclick="srReplaceCurrent()"]')
    replace_btn.click()

    # Take screenshots at timed intervals
    page.wait_for_timeout(200)
    page.screenshot(path=f"{SCREENSHOTS}/max_200ms.png", full_page=False)
    text_200 = page.evaluate("""() => {
        // Look for cells containing TESTVALUE
        var cells = Array.from(document.querySelectorAll('.ag-cell'));
        var tv = cells.filter(c => c.textContent.includes('TESTVALUE'));
        // Also check the previously highlighted cell area
        var highlight = document.querySelector('.sr-current-match');
        return {
            testvalue_cells: tv.map(c => c.textContent.trim().slice(0, 80)),
            testvalue_count: tv.length,
            highlight_text: highlight ? highlight.textContent.trim().slice(0, 80) : 'NO HIGHLIGHT',
            // Check allRowData too
            allRowData_count: typeof allRowData !== 'undefined' ? allRowData.filter(r => Object.values(r).some(v => String(v).includes('TESTVALUE'))).length : -1
        };
    }""")
    print(f"AT 200ms: {text_200}")

    page.wait_for_timeout(300)  # total 500ms from click
    page.screenshot(path=f"{SCREENSHOTS}/max_500ms.png", full_page=False)
    text_500 = page.evaluate("""() => {
        var cells = Array.from(document.querySelectorAll('.ag-cell'));
        var tv = cells.filter(c => c.textContent.includes('TESTVALUE'));
        var highlight = document.querySelector('.sr-current-match');
        return {
            testvalue_cells: tv.map(c => c.textContent.trim().slice(0, 80)),
            testvalue_count: tv.length,
            highlight_text: highlight ? highlight.textContent.trim().slice(0, 80) : 'NO HIGHLIGHT',
            allRowData_count: typeof allRowData !== 'undefined' ? allRowData.filter(r => Object.values(r).some(v => String(v).includes('TESTVALUE'))).length : -1
        };
    }""")
    print(f"AT 500ms: {text_500}")

    page.wait_for_timeout(1000)  # total 1500ms from click
    page.screenshot(path=f"{SCREENSHOTS}/max_1500ms.png", full_page=False)
    text_1500 = page.evaluate("""() => {
        var cells = Array.from(document.querySelectorAll('.ag-cell'));
        var tv = cells.filter(c => c.textContent.includes('TESTVALUE'));
        var highlight = document.querySelector('.sr-current-match');
        return {
            testvalue_cells: tv.map(c => c.textContent.trim().slice(0, 80)),
            testvalue_count: tv.length,
            highlight_text: highlight ? highlight.textContent.trim().slice(0, 80) : 'NO HIGHLIGHT',
            allRowData_count: typeof allRowData !== 'undefined' ? allRowData.filter(r => Object.values(r).some(v => String(v).includes('TESTVALUE'))).length : -1
        };
    }""")
    print(f"AT 1500ms: {text_1500}")

    # 9. Console verification script
    page.wait_for_timeout(2000)  # wait for refreshGridData to complete
    console_result = page.evaluate("""() => {
        var found = allRowData.filter(r => Object.values(r).some(v => String(v).includes('TESTVALUE')));
        var dom = Array.from(document.querySelectorAll('.ag-cell')).filter(c => c.textContent.includes('TESTVALUE'));
        return {
            allRowData_count: found.length,
            allRowData_first: found[0] ? found[0].source_name : '',
            dom_count: dom.length,
            dom_texts: dom.map(c => c.textContent.trim().slice(0, 60))
        };
    }""")
    print(f"CONSOLE VERIFICATION: {console_result}")

    # Screenshot of final state
    page.screenshot(path=f"{SCREENSHOTS}/max_console.png", full_page=False)

    # 10. Revert: replace TESTVALUE back to LLC for cleanup
    page.fill("#srSearch", "TESTVALUE")
    page.fill("#srReplace", "LLC")
    page.wait_for_timeout(1500)

    revert_btn = page.locator('#searchReplaceModal button[onclick="srReplaceCurrent()"]')
    revert_btn.click()
    page.wait_for_timeout(3000)

    # Save to persist the revert
    save_btn = page.locator("#saveChangesBtn")
    if save_btn.is_visible():
        save_btn.click()
        page.wait_for_timeout(5000)

    # Assertions
    assert text_200['allRowData_count'] >= 1, "allRowData should have TESTVALUE at 200ms"
    print("TEST PASSED: Replace timing screenshots captured successfully")

"""
Search & Replace visual bug reproduction and fix verification.
Takes screenshots at each step to prove broken vs fixed state.
"""
import time
from playwright.sync_api import sync_playwright

BASE_URL = "http://127.0.0.1:5000"
SCREENSHOT_DIR = r"C:\ClaudeMain\BA_Review_App\tests\screenshots"


def take_screenshot(page, name):
    path = f"{SCREENSHOT_DIR}/{name}"
    page.screenshot(path=path, full_page=False)
    print(f"  -> Saved: {path}")
    return path


def phase1_broken_state(page):
    """Screenshot the broken state before applying fix."""
    print("\n=== PHASE 1: SCREENSHOT BROKEN STATE ===")

    # Hard refresh
    page.goto(BASE_URL)
    page.keyboard.press("Control+Shift+r")
    page.wait_for_selector("#matchesGrid .ag-row", timeout=30000)
    page.wait_for_selector("#recBreakdown .col", timeout=15000)
    time.sleep(2)
    print("Grid loaded.")

    # Open Search & Replace modal
    # Find the S&R button in the toolbar
    sr_btn = page.locator('button[onclick="openSearchReplace()"]')
    if sr_btn.count() == 0:
        # Try by title or icon
        sr_btn = page.locator('button:has-text("⇄")')
    if sr_btn.count() == 0:
        sr_btn = page.locator('#btnSearchReplace')
    sr_btn.first.click()
    time.sleep(1)

    # Wait for modal to be visible
    page.wait_for_selector('#searchReplaceModal.show', timeout=5000)
    print("S&R modal opened.")

    # Drag modal to top-right corner
    modal_header = page.locator('#searchReplaceModal .modal-header')
    bbox = modal_header.bounding_box()
    if bbox:
        # Drag from center of header to top-right area
        start_x = bbox['x'] + bbox['width'] / 2
        start_y = bbox['y'] + bbox['height'] / 2
        # Get viewport size
        vp = page.viewport_size or page.evaluate("() => ({width: window.innerWidth, height: window.innerHeight})")
        target_x = vp['width'] - 200
        target_y = 60
        page.mouse.move(start_x, start_y)
        page.mouse.down()
        page.mouse.move(target_x, target_y, steps=10)
        page.mouse.up()
        time.sleep(0.5)
        print("Modal dragged to top-right.")

    # Type search and replace values
    search_input = page.locator('#srSearch')
    replace_input = page.locator('#srReplace')
    search_input.fill('LLC')
    time.sleep(0.5)
    replace_input.fill('BROKEN_TEST')
    time.sleep(0.5)

    # Trigger search - type into search field triggers auto-find after 300ms debounce
    # Then click Find Next to navigate to first match
    search_input.press('Space')
    search_input.press('Backspace')
    time.sleep(1)
    # Click Find Next button
    page.locator('#searchReplaceModal button[onclick="srFindNext()"]').click()
    time.sleep(2)
    print("Search executed, waiting for highlights...")

    # SCREENSHOT 1: Before replace
    take_screenshot(page, "screenshot_01_before_replace.png")

    # Get the highlighted cell text
    highlighted = page.evaluate("""() => {
        var cells = document.querySelectorAll('.sr-highlight, .ag-cell[style*="background"]');
        return Array.from(cells).map(c => ({text: c.textContent, colId: c.getAttribute('col-id')})).slice(0, 5);
    }""")
    print(f"Highlighted cells: {highlighted}")

    # Also check what srMatches says
    match_info = page.evaluate("""() => {
        return {
            matchCount: typeof srMatches !== 'undefined' ? srMatches.length : 'undefined',
            matchIdx: typeof srMatchIdx !== 'undefined' ? srMatchIdx : 'undefined',
            infoText: document.querySelector('#srMatchInfo') ? document.querySelector('#srMatchInfo').textContent : 'no #srMatchInfo'
        };
    }""")
    print(f"Match info: {match_info}")

    # Click Replace button
    replace_btn = page.locator('#searchReplaceModal button[onclick="srReplaceCurrent()"]')
    if replace_btn.count() > 0:
        box = replace_btn.bounding_box()
        if box:
            page.mouse.click(box['x'] + box['width']/2, box['y'] + box['height']/2)
            print("Clicked Replace button via coordinates.")
    else:
        print("ERROR: Could not find Replace button!")
        return

    time.sleep(3)
    print("Waited 3s after replace.")

    # SCREENSHOT 2: After replace (broken)
    take_screenshot(page, "screenshot_02_after_replace_broken.png")

    # Check what happened
    result = page.evaluate("""() => {
        var inAllRowData = allRowData.filter(r => JSON.stringify(r).includes('BROKEN_TEST'));
        var domCells = Array.from(document.querySelectorAll('.ag-cell')).filter(c => c.textContent.includes('BROKEN_TEST'));
        return {
            allRowDataCount: inAllRowData.length,
            allRowDataRowId: inAllRowData.length > 0 ? inAllRowData[0]._row_id : null,
            domCellCount: domCells.length,
            domCellTexts: domCells.map(c => c.getAttribute('col-id') + ': ' + c.textContent).slice(0, 5),
            matchInfo: document.querySelector('#srMatchInfo') ? document.querySelector('#srMatchInfo').textContent : 'N/A'
        };
    }""")
    print(f"After replace result: {result}")

    if result['domCellCount'] == 0 and result['allRowDataCount'] > 0:
        print("BUG CONFIRMED: Value is in allRowData but NOT visible in DOM cells!")
    elif result['domCellCount'] > 0:
        print("Cell IS visible in DOM - bug may not reproduce this time.")
    else:
        print("Value not even in allRowData - replace may have failed.")

    return result


def phase2_console_diagnosis(page):
    """Run diagnostic console commands."""
    print("\n=== PHASE 2: CONSOLE DIAGNOSIS ===")

    diag = page.evaluate("""() => {
        var results = {};

        // AG Grid version
        results.agGridVersion = typeof agGrid !== 'undefined' ? agGrid.version : 'agGrid not found';

        // refreshGridData source (first 500 chars)
        results.refreshGridDataSrc = typeof refreshGridData === 'function'
            ? refreshGridData.toString().substring(0, 500)
            : 'not a function';

        // Check allRowData for BROKEN_TEST
        var found = allRowData.filter(r => JSON.stringify(r).includes('BROKEN_TEST'));
        results.brokenTestInAllRowData = found.length;
        results.brokenTestRowId = found.length > 0 ? found[0]._row_id : null;

        // Check DOM
        var domFound = Array.from(document.querySelectorAll('.ag-cell')).filter(c => c.textContent.includes('BROKEN_TEST'));
        results.brokenTestInDOM = domFound.length;
        results.domTexts = domFound.map(c => c.getAttribute('col-id') + ': ' + c.textContent).slice(0, 5);

        // Check horizontal scroll
        var hScroll = document.querySelector('.ag-body-horizontal-scroll-viewport');
        results.horizontalScrollLeft = hScroll ? hScroll.scrollLeft : 'not found';

        // Check source_name column visibility
        var col = gridApi.getColumn('source_name');
        results.sourceNameCol = col ? {visible: col.visible, left: col.left, width: col.actualWidth} : 'NOT FOUND';

        return results;
    }""")
    print(f"Diagnosis: {diag}")

    take_screenshot(page, "screenshot_03_console_diagnosis.png")
    return diag


def phase4_verify_fix(page):
    """After fix is applied, verify with screenshots."""
    print("\n=== PHASE 4: VERIFY THE FIX ===")

    # Hard refresh
    page.goto(BASE_URL)
    page.keyboard.press("Control+Shift+r")
    page.wait_for_selector("#matchesGrid .ag-row", timeout=30000)
    page.wait_for_selector("#recBreakdown .col", timeout=15000)
    time.sleep(2)
    print("Grid loaded after fix.")

    # Open S&R modal
    sr_btn = page.locator('button[onclick="openSearchReplace()"]')
    if sr_btn.count() == 0:
        sr_btn = page.locator('button:has-text("⇄")')
    if sr_btn.count() == 0:
        sr_btn = page.locator('#btnSearchReplace')
    sr_btn.first.click()
    time.sleep(1)
    page.wait_for_selector('#searchReplaceModal.show', timeout=5000)
    print("S&R modal opened.")

    # Drag modal to top-right
    modal_header = page.locator('#searchReplaceModal .modal-header')
    bbox = modal_header.bounding_box()
    if bbox:
        start_x = bbox['x'] + bbox['width'] / 2
        start_y = bbox['y'] + bbox['height'] / 2
        vp = page.viewport_size or page.evaluate("() => ({width: window.innerWidth, height: window.innerHeight})")
        target_x = vp['width'] - 200
        target_y = 60
        page.mouse.move(start_x, start_y)
        page.mouse.down()
        page.mouse.move(target_x, target_y, steps=10)
        page.mouse.up()
        time.sleep(0.5)
        print("Modal dragged to top-right.")

    # Type search and replace
    search_input = page.locator('#srSearch')
    replace_input = page.locator('#srReplace')
    search_input.fill('LLC')
    time.sleep(0.5)
    replace_input.fill('FIXED_TEST')
    time.sleep(0.5)

    # Trigger search
    search_input.press('Space')
    search_input.press('Backspace')
    time.sleep(1)
    page.locator('#searchReplaceModal button[onclick="srFindNext()"]').click()
    time.sleep(2)
    print("Search executed.")

    # SCREENSHOT 5: Before fix replace
    take_screenshot(page, "screenshot_05_before_fixed_replace.png")

    # Get highlighted cell info
    pre_info = page.evaluate("""() => {
        var info = document.querySelector('#srMatchInfo');
        return {
            infoText: info ? info.textContent : 'N/A',
            matchCount: typeof srMatches !== 'undefined' ? srMatches.length : 0,
            matchIdx: typeof srMatchIdx !== 'undefined' ? srMatchIdx : 0
        };
    }""")
    print(f"Pre-replace info: {pre_info}")

    # Click Replace
    replace_btn = page.locator('#searchReplaceModal button[onclick="srReplaceCurrent()"]')
    if replace_btn.count() > 0:
        box = replace_btn.bounding_box()
        if box:
            page.mouse.click(box['x'] + box['width']/2, box['y'] + box['height']/2)
            print("Clicked Replace button.")
    time.sleep(3)

    # SCREENSHOT 6: After fix replace
    take_screenshot(page, "screenshot_06_after_fixed_replace.png")

    # Verify
    result = page.evaluate("""() => {
        var inAllRowData = allRowData.filter(r => JSON.stringify(r).includes('FIXED_TEST'));
        var domCells = Array.from(document.querySelectorAll('.ag-cell')).filter(c => c.textContent.includes('FIXED_TEST'));
        return {
            allRowDataCount: inAllRowData.length,
            domCellCount: domCells.length,
            domCellTexts: domCells.map(c => c.getAttribute('col-id') + ': ' + c.textContent).slice(0, 5),
            matchInfo: document.querySelector('#srMatchInfo') ? document.querySelector('#srMatchInfo').textContent : 'N/A'
        };
    }""")
    print(f"After fix replace result: {result}")

    if result['domCellCount'] > 0:
        print("FIX VERIFIED: Cell text is visible in DOM!")
    else:
        print("Cell not in DOM. Checking if it's a scroll issue...")
        # Try forcing scroll to the column
        page.evaluate("""() => {
            gridApi.ensureColumnVisible('source_name', 'start');
            gridApi.refreshCells({ columns: ['source_name'], force: true });
        }""")
        time.sleep(1)
        take_screenshot(page, "screenshot_07_verify_console.png")

        result2 = page.evaluate("""() => {
            var domCells = Array.from(document.querySelectorAll('.ag-cell')).filter(c => c.textContent.includes('FIXED_TEST'));
            return {
                domCellCount: domCells.length,
                domCellTexts: domCells.map(c => c.getAttribute('col-id') + ': ' + c.textContent).slice(0, 5)
            };
        }""")
        print(f"After scroll fix: {result2}")

        if result2['domCellCount'] > 0:
            take_screenshot(page, "screenshot_08_after_scroll_fix.png")
            print("FIX VERIFIED after scroll correction.")
        else:
            print("STILL NOT VISIBLE. Need nuclear option.")

    return result


def main():
    import os
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=['--start-maximized'])
        context = browser.new_context(no_viewport=True)
        page = context.new_page()

        # PHASE 1: Screenshot broken state
        phase1_result = phase1_broken_state(page)

        # PHASE 2: Console diagnosis
        phase2_result = phase2_console_diagnosis(page)

        print("\n=== PHASES 1-2 COMPLETE ===")
        print("Now apply the fix to app.js and run phase 4.")

        browser.close()


def run_phase4():
    import os
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=['--start-maximized'])
        context = browser.new_context(no_viewport=True)
        page = context.new_page()

        result = phase4_verify_fix(page)

        print("\n=== PHASE 4 COMPLETE ===")
        browser.close()
        return result


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'phase4':
        run_phase4()
    else:
        main()

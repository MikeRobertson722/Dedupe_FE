"""
Visual proof that clicking Replace in S&R modal changes cell text.
Takes ZOOMED-IN screenshots showing before/after cell content.
"""
import time
import json
from playwright.sync_api import sync_playwright

BASE_URL = "http://127.0.0.1:5000"
SCREENSHOT_DIR = r"C:\ClaudeMain\BA_Review_App\tests\screenshots"


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--start-maximized"])
        context = browser.new_context(no_viewport=True)
        page = context.new_page()

        # 1. Navigate and wait for grid
        page.goto(BASE_URL)
        page.wait_for_selector("#matchesGrid .ag-row", timeout=30000)
        page.wait_for_selector("#recBreakdown .col", timeout=15000)
        print("Grid loaded.")

        # 2. Hard refresh
        page.keyboard.press("Control+Shift+r")
        page.wait_for_selector("#matchesGrid .ag-row", timeout=30000)
        page.wait_for_selector("#recBreakdown .col", timeout=15000)
        time.sleep(2)
        print("Hard refresh done.")

        # 3. Zoom to 200% (Ctrl+Plus 4 times)
        for i in range(4):
            page.keyboard.press("Control+=")
            time.sleep(0.3)
        print("Zoomed to ~200%.")

        # 4. Open Search & Replace modal
        # Click the S&R toolbar button (it uses onclick="openSearchReplace()")
        page.click("button[onclick='openSearchReplace()']", timeout=5000)
        page.wait_for_selector("#searchReplaceModal.show", timeout=5000)
        time.sleep(0.5)
        print("S&R modal open.")

        # 5. Drag modal to top-right corner
        modal_dialog = page.query_selector("#searchReplaceModal .modal-dialog")
        if modal_dialog:
            box = modal_dialog.bounding_box()
            if box:
                # Drag from center of modal header to top-right
                page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 15)
                page.mouse.down()
                vp = page.evaluate("() => ({ w: window.innerWidth, h: window.innerHeight })")
                page.mouse.move(vp["w"] - box["width"] / 2 - 20, 20, steps=10)
                page.mouse.up()
                time.sleep(0.3)
                print("Modal dragged to top-right.")

        # 6. Type search and replace values
        search_input = page.query_selector("#srSearch")
        replace_input = page.query_selector("#srReplace")
        search_input.fill("OIL")
        replace_input.fill("OIL_REPLACED")
        # Trigger the search
        page.click("#srSearch")
        page.keyboard.press("Enter")
        time.sleep(2)  # Wait for highlights
        print("Search/Replace values entered, waiting for highlights.")

        # 7. Get info about the current match before replace
        before_info = page.evaluate("""() => {
            var info = {};
            // Get match info
            info.matchCount = srMatches ? srMatches.length : 0;
            info.matchIdx = typeof srMatchIdx !== 'undefined' ? srMatchIdx : -1;
            if (srMatches && srMatches.length > 0) {
                var m = srMatches[info.matchIdx];
                info.matchCol = m.col;
                info.matchRowId = m.rowId;
                // Get the actual cell value from allRowData
                var row = allRowData.find(r => String(r.uid) === String(m.rowId));
                if (row) {
                    info.cellValue = row[m.col];
                    info.sourceName = row.source_name;
                }
            }
            // Check highlighted cell in DOM
            var hlCell = document.querySelector('.sr-highlight-current');
            if (hlCell) {
                info.hlCellText = hlCell.textContent.trim();
                info.hlCellRect = JSON.parse(JSON.stringify(hlCell.getBoundingClientRect()));
            }
            return info;
        }""")
        print(f"BEFORE info: {json.dumps(before_info, indent=2)}")

        # 8. Widen the source_name column - find its header and drag
        page.evaluate("""() => {
            var col = gridApi.getColumn('source_name');
            if (col) {
                gridApi.setColumnWidth('source_name', 400);
            }
        }""")
        time.sleep(0.5)

        # Ensure the highlighted cell is visible
        page.evaluate("""() => {
            if (srMatches && srMatches.length > 0) {
                var m = srMatches[srMatchIdx];
                gridApi.ensureColumnVisible(m.col, 'start');
                var node = gridApi.getRowNode(String(m.rowId));
                if (node) gridApi.ensureNodeVisible(node, 'middle');
            }
        }""")
        time.sleep(1)

        # ==================== SCREENSHOT 1: BEFORE ====================
        page.screenshot(path=f"{SCREENSHOT_DIR}/proof_before.png", full_page=False)
        print("SCREENSHOT 1 (proof_before.png) taken.")

        # Also capture a zoomed clip of just the highlighted cell area
        hl_rect = page.evaluate("""() => {
            var hlCell = document.querySelector('.sr-highlight-current');
            if (hlCell) {
                var r = hlCell.getBoundingClientRect();
                return { x: r.x, y: r.y, width: r.width, height: r.height };
            }
            return null;
        }""")

        if hl_rect:
            # Take a clipped screenshot of the cell with padding
            pad = 30
            clip_x = max(0, hl_rect["x"] - pad)
            clip_y = max(0, hl_rect["y"] - pad)
            clip_w = hl_rect["width"] + pad * 2
            clip_h = hl_rect["height"] + pad * 2
            page.screenshot(
                path=f"{SCREENSHOT_DIR}/proof_before_cell_zoom.png",
                clip={"x": clip_x, "y": clip_y, "width": clip_w, "height": clip_h}
            )
            print(f"SCREENSHOT 1b (cell zoom) taken. Cell rect: {hl_rect}")

        # Record the cell text BEFORE
        before_cell_text = page.evaluate("""() => {
            var hlCell = document.querySelector('.sr-highlight-current');
            return hlCell ? hlCell.textContent.trim() : 'NO HIGHLIGHTED CELL FOUND';
        }""")
        print(f"BEFORE cell text: '{before_cell_text}'")

        # ==================== CLICK REPLACE ====================
        # Use the exact selector from memory
        replace_btn = page.query_selector('#searchReplaceModal button[onclick="srReplaceCurrent()"]')
        if replace_btn:
            box = replace_btn.bounding_box()
            if box:
                cx = box["x"] + box["width"] / 2
                cy = box["y"] + box["height"] / 2
                page.mouse.click(cx, cy)
                print(f"Clicked Replace button at ({cx}, {cy}).")
            else:
                replace_btn.click()
                print("Clicked Replace button (fallback).")
        else:
            print("ERROR: Replace button not found!")

        # ==================== SCREENSHOT 2: AT 300ms ====================
        time.sleep(0.3)
        page.screenshot(path=f"{SCREENSHOT_DIR}/proof_300ms.png", full_page=False)
        print("SCREENSHOT 2 (proof_300ms.png) taken at 300ms.")

        # Get the cell text at 300ms
        text_300 = page.evaluate("""() => {
            var results = {};
            // Check allRowData
            var replaced = allRowData.filter(r => JSON.stringify(r).includes('OIL_REPLACED'));
            results.allRowDataCount = replaced.length;
            results.allRowDataValue = replaced.length > 0 ? replaced[0].source_name : '';
            // Check DOM
            var domCells = Array.from(document.querySelectorAll('.ag-cell')).filter(c => c.textContent.includes('OIL_REPLACED'));
            results.domCellCount = domCells.length;
            results.domCellText = domCells.length > 0 ? domCells[0].textContent.trim() : '';
            // Check highlighted cell
            var hlCell = document.querySelector('.sr-highlight-current');
            results.hlCellText = hlCell ? hlCell.textContent.trim() : 'NO HL CELL';
            results.hlCellRect = hlCell ? JSON.parse(JSON.stringify(hlCell.getBoundingClientRect())) : null;
            return results;
        }""")
        print(f"AT 300ms: {json.dumps(text_300, indent=2)}")

        # Take zoomed cell screenshot at 300ms
        hl_rect2 = text_300.get("hlCellRect")
        if hl_rect2:
            pad = 30
            clip_x = max(0, hl_rect2["x"] - pad)
            clip_y = max(0, hl_rect2["y"] - pad)
            clip_w = hl_rect2["width"] + pad * 2
            clip_h = hl_rect2["height"] + pad * 2
            page.screenshot(
                path=f"{SCREENSHOT_DIR}/proof_300ms_cell_zoom.png",
                clip={"x": clip_x, "y": clip_y, "width": clip_w, "height": clip_h}
            )
            print("SCREENSHOT 2b (300ms cell zoom) taken.")

        # ==================== SCREENSHOT 3: AT 700ms ====================
        time.sleep(0.4)
        page.screenshot(path=f"{SCREENSHOT_DIR}/proof_700ms.png", full_page=False)
        print("SCREENSHOT 3 (proof_700ms.png) taken at 700ms.")

        # Get the cell text at 700ms
        text_700 = page.evaluate("""() => {
            var results = {};
            var replaced = allRowData.filter(r => JSON.stringify(r).includes('OIL_REPLACED'));
            results.allRowDataCount = replaced.length;
            results.allRowDataValue = replaced.length > 0 ? replaced[0].source_name : '';
            var domCells = Array.from(document.querySelectorAll('.ag-cell')).filter(c => c.textContent.includes('OIL_REPLACED'));
            results.domCellCount = domCells.length;
            results.domCellText = domCells.length > 0 ? domCells[0].textContent.trim() : '';
            var hlCell = document.querySelector('.sr-highlight-current');
            results.hlCellText = hlCell ? hlCell.textContent.trim() : 'NO HL CELL';
            results.hlCellRect = hlCell ? JSON.parse(JSON.stringify(hlCell.getBoundingClientRect())) : null;
            return results;
        }""")
        print(f"AT 700ms: {json.dumps(text_700, indent=2)}")

        # Take zoomed cell screenshot at 700ms
        hl_rect3 = text_700.get("hlCellRect")
        if hl_rect3:
            pad = 30
            clip_x = max(0, hl_rect3["x"] - pad)
            clip_y = max(0, hl_rect3["y"] - pad)
            clip_w = hl_rect3["width"] + pad * 2
            clip_h = hl_rect3["height"] + pad * 2
            page.screenshot(
                path=f"{SCREENSHOT_DIR}/proof_700ms_cell_zoom.png",
                clip={"x": clip_x, "y": clip_y, "width": clip_w, "height": clip_h}
            )
            print("SCREENSHOT 3b (700ms cell zoom) taken.")

        # Wait a bit more for full render, then take a final clean screenshot
        time.sleep(1)

        # ==================== FINAL: Console verification ====================
        console_check = page.evaluate("""() => {
            var replaced = allRowData.filter(r => JSON.stringify(r).includes('OIL_REPLACED'));
            var dom = Array.from(document.querySelectorAll('.ag-cell')).filter(c => c.textContent.includes('OIL_REPLACED'));
            return {
                DATA_count: replaced.length,
                DATA_source_name: replaced.length > 0 ? replaced[0].source_name : '',
                DOM_count: dom.length,
                DOM_text: dom.length > 0 ? dom[0].textContent.trim() : ''
            };
        }""")
        print(f"\nFINAL CONSOLE CHECK: {json.dumps(console_check, indent=2)}")

        # Ensure the replaced cell is scrolled into view for final screenshot
        page.evaluate("""() => {
            var replaced = allRowData.filter(r => JSON.stringify(r).includes('OIL_REPLACED'));
            if (replaced.length > 0) {
                var node = gridApi.getRowNode(String(replaced[0].uid));
                if (node) {
                    gridApi.ensureNodeVisible(node, 'middle');
                    gridApi.ensureColumnVisible('source_name', 'start');
                }
            }
        }""")
        time.sleep(0.5)

        page.screenshot(path=f"{SCREENSHOT_DIR}/proof_console.png", full_page=False)
        print("SCREENSHOT 4 (proof_console.png) taken.")

        # Take zoomed screenshot of the replaced cell for final proof
        final_cell_rect = page.evaluate("""() => {
            var domCells = Array.from(document.querySelectorAll('.ag-cell')).filter(c => c.textContent.includes('OIL_REPLACED'));
            if (domCells.length > 0) {
                var r = domCells[0].getBoundingClientRect();
                return { x: r.x, y: r.y, width: r.width, height: r.height, text: domCells[0].textContent.trim() };
            }
            return null;
        }""")

        if final_cell_rect:
            pad = 40
            clip_x = max(0, final_cell_rect["x"] - pad)
            clip_y = max(0, final_cell_rect["y"] - pad)
            clip_w = final_cell_rect["width"] + pad * 2
            clip_h = final_cell_rect["height"] + pad * 2
            page.screenshot(
                path=f"{SCREENSHOT_DIR}/proof_console_cell_zoom.png",
                clip={"x": clip_x, "y": clip_y, "width": clip_w, "height": clip_h}
            )
            print(f"Final cell zoom taken. Cell text: '{final_cell_rect['text']}'")

        # ==================== REVERT the change ====================
        # Undo the replace so we don't leave dirty data
        page.evaluate("""() => {
            if (typeof performUndo === 'function') performUndo();
        }""")
        time.sleep(0.5)
        print("Undo performed to revert test change.")

        # Summary
        print("\n" + "=" * 60)
        print("VISUAL PROOF SUMMARY")
        print("=" * 60)
        print(f"BEFORE cell text:  '{before_cell_text}'")
        print(f"AT 300ms DOM text: '{text_300.get('domCellText', 'N/A')}'")
        print(f"AT 300ms HL text:  '{text_300.get('hlCellText', 'N/A')}'")
        print(f"AT 700ms DOM text: '{text_700.get('domCellText', 'N/A')}'")
        print(f"AT 700ms HL text:  '{text_700.get('hlCellText', 'N/A')}'")
        print(f"FINAL DATA count:  {console_check['DATA_count']}")
        print(f"FINAL DOM count:   {console_check['DOM_count']}")
        print(f"FINAL source_name: '{console_check['DATA_source_name']}'")
        print("=" * 60)

        browser.close()


if __name__ == "__main__":
    run()

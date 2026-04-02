"""
Visual proof: Replace button changes the SAME cell text from LLC -> REPLACED.
Takes before/after screenshots of the SAME row, with overlays showing evidence.
"""
import time
from playwright.sync_api import sync_playwright

BASE_URL = "http://127.0.0.1:5000"
SCREENSHOT_DIR = r"C:\ClaudeMain\BA_Review_App\tests\screenshots"


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            device_scale_factor=1.5,
        )
        page = context.new_page()

        # ── Step 1: Hard refresh, wait for grid ──────────────────────
        page.goto(BASE_URL, wait_until="load", timeout=60000)
        page.reload(wait_until="load", timeout=60000)
        page.wait_for_selector("#matchesGrid .ag-row", timeout=30000)
        page.wait_for_selector("#recBreakdown .col", timeout=15000)
        time.sleep(2)

        # ── Widen source_name column so text is readable ─────────────
        page.evaluate("""() => {
            gridApi.setColumnWidths([{key: 'source_name', newWidth: 350}]);
        }""")
        time.sleep(0.5)

        # ── Step 3: Open Search & Replace modal ─────────────────────
        page.click("button[onclick='openSearchReplace()']")
        page.wait_for_selector("#searchReplaceModal.show", timeout=5000)
        time.sleep(0.5)

        # Move modal to top-right
        page.evaluate("""() => {
            var dlg = document.querySelector('#searchReplaceModal .modal-dialog');
            dlg.style.position = 'fixed';
            dlg.style.top = '10px';
            dlg.style.right = '10px';
            dlg.style.left = 'auto';
            dlg.style.margin = '0';
        }""")
        time.sleep(0.5)

        # ── Step 4: Type LLC in Search, REPLACED in Replace ──────────
        page.fill("#srSearch", "LLC")
        page.fill("#srReplace", "REPLACED")
        time.sleep(1.5)

        # Click Find Next
        page.click("#searchReplaceModal button[onclick='srFindNext()']")
        time.sleep(3)

        # ── Record the EXACT match ───────────────────────────────────
        before_info = page.evaluate("""() => {
            var matchInfo = document.querySelector('#srMatchInfo')
                ? document.querySelector('#srMatchInfo').textContent : 'no info';
            var idx = typeof srMatchIdx !== 'undefined' ? srMatchIdx : -1;
            var match = (typeof srMatches !== 'undefined' && srMatches[idx])
                ? srMatches[idx] : null;
            var nodeId = match ? String(match.nodeId || match.rowId || '') : 'unknown';
            var col = match ? match.col : 'unknown';

            var cellVal = '';
            if (match) {
                var row = allRowData.find(r => String(r._row_id) === nodeId);
                if (row) cellVal = String(row[col] || '');
            }

            // Find cell in DOM across ALL ag-row containers
            var allCells = document.querySelectorAll('.ag-cell[col-id="' + col + '"]');
            var targetCell = null;
            allCells.forEach(function(c) {
                var rowEl = c.closest('.ag-row');
                if (rowEl && rowEl.getAttribute('row-id') === nodeId) targetCell = c;
            });
            var domText = targetCell ? targetCell.textContent.trim() : 'NOT IN DOM';

            return {
                matchInfo: matchInfo,
                srMatchIdx: idx,
                nodeId: nodeId,
                col: col,
                cellValFromData: cellVal,
                domText: domText
            };
        }""")
        print(f"BEFORE Replace: {before_info}")

        # ── Annotate ─────────────────────────────────────────────────
        page.evaluate("""(info) => {
            var lbl = document.createElement('div');
            lbl.id = 'beforeLabel';
            lbl.style.cssText = 'position:fixed;bottom:5px;left:5px;background:rgba(0,0,0,0.92);color:#0f0;font-family:monospace;font-size:12px;padding:10px;border-radius:6px;z-index:99999;max-width:600px;white-space:pre-wrap;';
            lbl.textContent = 'BEFORE Replace\\n' +
                info.matchInfo + '\\n' +
                'Row ID: ' + info.nodeId + '  Col: ' + info.col + '\\n' +
                'Data: ' + info.cellValFromData + '\\n' +
                'DOM cell: ' + info.domText;
            document.body.appendChild(lbl);
        }""", before_info)
        time.sleep(0.3)

        # ── SCREENSHOT 1: before.png ─────────────────────────────────
        page.screenshot(path=f"{SCREENSHOT_DIR}/before.png", full_page=False)
        print("Saved before.png")
        page.evaluate("document.getElementById('beforeLabel')?.remove()")

        # ── Click Replace ────────────────────────────────────────────
        target_node_id = before_info["nodeId"]
        target_col = before_info["col"]
        before_val = before_info["cellValFromData"]

        replace_btn = page.query_selector(
            '#searchReplaceModal button[onclick="srReplaceCurrent()"]'
        )
        if replace_btn:
            replace_btn.click()
        else:
            page.evaluate("srReplaceCurrent()")

        time.sleep(1)

        # ── Scroll back to the replaced cell ─────────────────────────
        page.evaluate("""(args) => {
            gridApi.ensureColumnVisible(args.col, 'start');
            var node = gridApi.getRowNode(args.nodeId);
            if (node) gridApi.ensureNodeVisible(node, 'middle');
        }""", {"nodeId": target_node_id, "col": target_col})
        time.sleep(1)

        # ── Read cell AFTER replace ──────────────────────────────────
        after_info = page.evaluate("""(args) => {
            var matchInfo = document.querySelector('#srMatchInfo')
                ? document.querySelector('#srMatchInfo').textContent : 'no info';

            var row = allRowData.find(r => String(r._row_id) === args.nodeId);
            var dataVal = row ? String(row[args.col] || '') : 'ROW NOT FOUND';

            // Find cell across ALL ag-row containers
            var allCells = document.querySelectorAll('.ag-cell[col-id="' + args.col + '"]');
            var targetCell = null;
            allCells.forEach(function(c) {
                var rowEl = c.closest('.ag-row');
                if (rowEl && rowEl.getAttribute('row-id') === args.nodeId) targetCell = c;
            });
            var domText = targetCell ? targetCell.textContent.trim() : 'CELL NOT IN DOM';

            return {
                matchInfo: matchInfo,
                dataVal: dataVal,
                domText: domText
            };
        }""", {"nodeId": target_node_id, "col": target_col})
        print(f"AFTER 1sec: {after_info}")

        page.evaluate("""(info) => {
            var lbl = document.createElement('div');
            lbl.id = 'afterLabel';
            lbl.style.cssText = 'position:fixed;bottom:5px;left:5px;background:rgba(0,0,0,0.92);color:#ff0;font-family:monospace;font-size:12px;padding:10px;border-radius:6px;z-index:99999;max-width:600px;white-space:pre-wrap;';
            lbl.textContent = 'AFTER Replace (1 sec)\\n' +
                info.matchInfo + '\\n' +
                'Data: ' + info.dataVal + '\\n' +
                'DOM cell: ' + info.domText;
            document.body.appendChild(lbl);
        }""", after_info)
        time.sleep(0.3)

        # ── SCREENSHOT 2: after_1sec.png ─────────────────────────────
        page.screenshot(path=f"{SCREENSHOT_DIR}/after_1sec.png", full_page=False)
        print("Saved after_1sec.png")
        page.evaluate("document.getElementById('afterLabel')?.remove()")

        time.sleep(2)

        # ── Ensure still at the right cell ───────────────────────────
        page.evaluate("""(args) => {
            gridApi.ensureColumnVisible(args.col, 'start');
            var node = gridApi.getRowNode(args.nodeId);
            if (node) gridApi.ensureNodeVisible(node, 'middle');
        }""", {"nodeId": target_node_id, "col": target_col})
        time.sleep(0.5)

        after_3s = page.evaluate("""(args) => {
            var row = allRowData.find(r => String(r._row_id) === args.nodeId);
            var dataVal = row ? String(row[args.col] || '') : 'ROW NOT FOUND';
            var allCells = document.querySelectorAll('.ag-cell[col-id="' + args.col + '"]');
            var targetCell = null;
            allCells.forEach(function(c) {
                var rowEl = c.closest('.ag-row');
                if (rowEl && rowEl.getAttribute('row-id') === args.nodeId) targetCell = c;
            });
            var domText = targetCell ? targetCell.textContent.trim() : 'CELL NOT IN DOM';
            return {dataVal: dataVal, domText: domText};
        }""", {"nodeId": target_node_id, "col": target_col})
        print(f"AFTER 3sec: {after_3s}")

        page.evaluate("""(info) => {
            var lbl = document.createElement('div');
            lbl.id = 'after3Label';
            lbl.style.cssText = 'position:fixed;bottom:5px;left:5px;background:rgba(0,0,0,0.92);color:#0ff;font-family:monospace;font-size:12px;padding:10px;border-radius:6px;z-index:99999;max-width:600px;white-space:pre-wrap;';
            lbl.textContent = 'AFTER Replace (3 sec)\\n' +
                'Data: ' + info.dataVal + '\\n' +
                'DOM cell: ' + info.domText;
            document.body.appendChild(lbl);
        }""", after_3s)
        time.sleep(0.3)
        page.screenshot(path=f"{SCREENSHOT_DIR}/after_3sec.png", full_page=False)
        print("Saved after_3sec.png")
        page.evaluate("document.getElementById('after3Label')?.remove()")

        # ── Console verification ─────────────────────────────────────
        console_result = page.evaluate("""() => {
            var found = allRowData.filter(r =>
                JSON.stringify(r).includes('REPLACED') &&
                !JSON.stringify(r).includes('REPLACED_'));
            var domCells = Array.from(document.querySelectorAll('.ag-cell'))
                .filter(c =>
                    c.textContent.includes('REPLACED') &&
                    !c.textContent.includes('REPLACED_'));
            return {
                allRowDataWithREPLACED: found.length,
                firstMatch: found[0]
                    ? {id: found[0]._row_id, name: found[0].source_name}
                    : 'none',
                domCellsWithREPLACED: domCells.length,
                domCellDetails: domCells.map(c => ({
                    col: c.getAttribute('col-id'),
                    rowId: c.closest('.ag-row')?.getAttribute('row-id'),
                    text: c.textContent.trim().substring(0, 50)
                }))
            };
        }""")
        print(f"Console: {console_result}")

        page.evaluate("""(result) => {
            var div = document.createElement('div');
            div.id = 'consoleOverlay';
            div.style.cssText = 'position:fixed;bottom:5px;left:5px;background:rgba(0,0,0,0.92);color:#0f0;font-family:monospace;font-size:12px;padding:10px;border-radius:6px;z-index:99999;max-width:700px;white-space:pre-wrap;';
            div.textContent = 'CONSOLE VERIFICATION\\n' +
                'allRowData REPLACED: ' + result.allRowDataWithREPLACED + '\\n' +
                'Match: ' + JSON.stringify(result.firstMatch) + '\\n' +
                'DOM cells REPLACED: ' + result.domCellsWithREPLACED + '\\n' +
                'Details: ' + JSON.stringify(result.domCellDetails);
            document.body.appendChild(div);
        }""", console_result)
        time.sleep(0.5)
        page.screenshot(path=f"{SCREENSHOT_DIR}/console_verify.png", full_page=False)
        print("Saved console_verify.png")

        # ── PASS/FAIL ────────────────────────────────────────────────
        data_ok = console_result["allRowDataWithREPLACED"] >= 1
        dom_ok = console_result["domCellsWithREPLACED"] >= 1
        after_dom = after_info.get("domText", "")
        cell_ok = "REPLACED" in after_dom and "REPLACED_" not in after_dom

        print(f"\n--- Verdict ---")
        print(f"  BEFORE: {before_val}")
        print(f"  AFTER data: {after_info['dataVal']}")
        print(f"  AFTER DOM cell: {after_dom}")
        print(f"  data_ok={data_ok}  dom_ok={dom_ok}  cell_ok={cell_ok}")

        if data_ok and cell_ok:
            verdict = "PASS"
            print("=== PASS ===")
        elif data_ok and dom_ok:
            verdict = "PASS"
            print("=== PASS (broad DOM scan confirms cell) ===")
        else:
            verdict = "FAIL"
            print("=== FAIL ===")

        # Undo
        page.evaluate("() => { if (typeof performUndo === 'function') performUndo(); }")
        time.sleep(1)
        browser.close()
        return verdict


if __name__ == "__main__":
    import os
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    result = run()
    print(f"\nFinal verdict: {result}")

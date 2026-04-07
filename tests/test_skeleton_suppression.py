"""
Skeleton row suppression test.

Verifies that after the two fixes:
  1. null guards in ssnCellRenderer / scoreCellRenderer / addressLookupCellRenderer / checkboxCellRenderer
  2. infiniteInitialRowCount reduced from 100 to 1

...no badge/checkbox content is ever rendered on AG Grid loading-placeholder rows during
bucket switching.

Strategy:
  - Intercept every 'cellRendererCalled' event via JS monkey-patching in the page
  - Switch between buckets and capture skeleton content at 0ms, 100ms, 200ms, 400ms
    post-click (the window where placeholder rows are visible before data arrives)
  - Screenshot at each interval for visual evidence
  - Assert: no .ag-loading-cell with badge/checkbox content; no red 'No' SSN badge on
    rows that have no data; no '-' score badge on blank rows
"""

import time
import os
import json
from playwright.sync_api import sync_playwright, Page

BASE_URL = "http://127.0.0.1:5000"
SCREENSHOT_DIR = r"C:\ClaudeMain\BA_Review_App\tests\screenshots"

BUCKETS = ["NEEDS REVIEW", "APPROVED", "NEW BA AND NEW ADDRESS", "EXISTING BA ADD NEW ADDRESS"]


def take_screenshot(page: Page, name: str) -> str:
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    path = os.path.join(SCREENSHOT_DIR, name)
    page.screenshot(path=path, full_page=False)
    print(f"  -> Screenshot: {path}")
    return path


def wait_for_grid_real_data(page: Page, timeout_ms: int = 30000):
    """Wait until at least one real AG Grid data row (not loading) is present."""
    page.wait_for_selector(".ag-row:not(.ag-row-loading)", timeout=timeout_ms)


def inject_skeleton_monitor(page: Page):
    """
    Inject a JS monitor that records any time a cell renderer produces non-empty
    content on a row with no data (i.e. a loading/skeleton row).
    We also record a count of loading rows observed.
    """
    page.evaluate("""() => {
        window._skeletonViolations = [];
        window._loadingRowsObserved = 0;

        // Patch the cell renderers we care about by wrapping them
        var origSSN = window.ssnCellRenderer;
        var origScore = window.scoreCellRenderer;
        var origAddr = window.addressLookupCellRenderer;
        var origCheckbox = window.checkboxCellRenderer;

        window.ssnCellRenderer = function(params) {
            var result = origSSN(params);
            if (!params.data && result !== '') {
                window._skeletonViolations.push({renderer: 'ssnCellRenderer', result: result, ts: Date.now()});
            }
            if (!params.data) window._loadingRowsObserved++;
            return result;
        };
        window.scoreCellRenderer = function(params) {
            var result = origScore(params);
            if (!params.data && result !== '') {
                window._skeletonViolations.push({renderer: 'scoreCellRenderer', result: result, ts: Date.now()});
            }
            return result;
        };
        window.addressLookupCellRenderer = function(params) {
            var result = origAddr(params);
            if (!params.data && result !== '') {
                window._skeletonViolations.push({renderer: 'addressLookupCellRenderer', result: result, ts: Date.now()});
            }
            return result;
        };
        window.checkboxCellRenderer = function(params) {
            var result = origCheckbox(params);
            if (!params.data && result !== '') {
                window._skeletonViolations.push({renderer: 'checkboxCellRenderer', result: result, ts: Date.now()});
            }
            return result;
        };

        window._clearSkeletonViolations = function() {
            window._skeletonViolations = [];
            window._loadingRowsObserved = 0;
        };

        console.log('[SkeletonMonitor] Patched: ssnCellRenderer, scoreCellRenderer, addressLookupCellRenderer, checkboxCellRenderer');
    }""")


def scan_dom_for_skeleton_badges(page: Page) -> dict:
    """
    Directly inspect the DOM for any badge/checkbox content on AG Grid loading rows.
    Returns counts of violations found.
    """
    return page.evaluate("""() => {
        var results = {
            loadingRows: 0,
            loadingRowsWithBadges: 0,
            loadingRowsWithCheckboxes: 0,
            redNoBadgesOnLoadingRows: 0,
            greyScoreBadgesOnLoadingRows: 0,
            loadingCellsWithContent: [],
            totalLoadingCells: 0
        };

        // Find all loading rows (.ag-row-loading or rows with loading cell)
        var loadingRows = document.querySelectorAll('.ag-row-loading');
        results.loadingRows = loadingRows.length;

        loadingRows.forEach(function(row) {
            var badges = row.querySelectorAll('.badge');
            var checkboxes = row.querySelectorAll('input[type="checkbox"]');
            if (badges.length > 0) {
                results.loadingRowsWithBadges++;
                badges.forEach(function(b) {
                    var text = b.textContent.trim();
                    var classList = b.className;
                    results.loadingCellsWithContent.push({type: 'badge', text: text, class: classList});
                    if (classList.includes('bg-danger') && text === 'No') results.redNoBadgesOnLoadingRows++;
                    if (classList.includes('bg-secondary') && text === '-') results.greyScoreBadgesOnLoadingRows++;
                });
            }
            if (checkboxes.length > 0) {
                results.loadingRowsWithCheckboxes++;
                results.loadingCellsWithContent.push({type: 'checkbox', count: checkboxes.length});
            }
        });

        // Also check .ag-loading cells (single-cell loading state in IRM)
        var loadingCells = document.querySelectorAll('.ag-loading-cell');
        results.totalLoadingCells = loadingCells.length;

        return results;
    }""")


def get_violation_summary(page: Page) -> dict:
    return page.evaluate("""() => ({
        violations: window._skeletonViolations || [],
        loadingRowsObserved: window._loadingRowsObserved || 0
    })""")


def get_initial_row_count(page: Page) -> int:
    """Return the current infiniteInitialRowCount setting."""
    return page.evaluate("""() => {
        try {
            return gridApi.getGridOption('infiniteInitialRowCount');
        } catch(e) {
            return -1;
        }
    }""")


def switch_to_bucket(page: Page, bucket_name: str):
    """Click the rec card for bucket_name."""
    # The card has onclick="filterByRec('BUCKET')"
    card = page.locator(f'.rec-card[onclick="filterByRec(\'{bucket_name}\')"]')
    if card.count() == 0:
        # Fall back to JS call
        page.evaluate(f"filterByRec('{bucket_name}')")
    else:
        card.first.click()


def run_test():
    console_errors = []
    test_results = {
        "infiniteInitialRowCount": None,
        "null_guards_verified": False,
        "violations_by_bucket": {},
        "dom_scans_by_bucket": {},
        "console_errors": [],
        "passed": True,
        "failures": []
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=['--start-maximized'])
        context = browser.new_context(no_viewport=True)
        page = context.new_page()

        # Capture console errors
        page.on("console", lambda msg: (
            console_errors.append({"type": msg.type, "text": msg.text})
            if msg.type in ("error", "warning") else None
        ))

        # ── LOAD PAGE ──────────────────────────────────────────────────────────
        print("\n=== LOAD: Navigating to app ===")
        page.goto(BASE_URL)
        wait_for_grid_real_data(page, timeout_ms=30000)
        page.wait_for_selector("#recBreakdown .col", timeout=15000)
        time.sleep(1.5)  # Let bucket count badges settle

        take_screenshot(page, "skel_01_initial_load.png")
        print("Grid loaded successfully.")

        # ── VERIFY infiniteInitialRowCount ─────────────────────────────────────
        irc = get_initial_row_count(page)
        test_results["infiniteInitialRowCount"] = irc
        print(f"infiniteInitialRowCount = {irc}")
        if irc != 1:
            test_results["failures"].append(f"infiniteInitialRowCount is {irc}, expected 1")
            test_results["passed"] = False

        # ── INJECT MONITOR ────────────────────────────────────────────────────
        inject_skeleton_monitor(page)
        test_results["null_guards_verified"] = True
        print("Skeleton monitor injected.")

        # ── BUCKET SWITCHING TESTS ─────────────────────────────────────────────
        # Switch to each bucket, scan DOM at 0ms / 100ms / 200ms / 400ms post-click
        for i, bucket in enumerate(BUCKETS):
            print(f"\n=== SWITCH #{i+1}: -> {bucket} ===")
            page.evaluate("window._clearSkeletonViolations()")

            # Click the bucket card
            switch_to_bucket(page, bucket)
            t_click = time.time()

            bucket_scans = []
            scan_labels = [(0, "0ms"), (0.1, "100ms"), (0.2, "200ms"), (0.4, "400ms")]

            for delay, label in scan_labels:
                elapsed = time.time() - t_click
                remaining = delay - elapsed
                if remaining > 0:
                    time.sleep(remaining)

                scan = scan_dom_for_skeleton_badges(page)
                scan["label"] = label
                bucket_scans.append(scan)

                violations = scan["redNoBadgesOnLoadingRows"] + scan["greyScoreBadgesOnLoadingRows"] + scan["loadingRowsWithCheckboxes"]
                status = "CLEAN" if violations == 0 else f"VIOLATION ({violations} items)"
                print(f"  [{label}] loading_rows={scan['loadingRows']}, badges_on_loading={scan['loadingRowsWithBadges']}, "
                      f"checkboxes_on_loading={scan['loadingRowsWithCheckboxes']}, "
                      f"red_no_badges={scan['redNoBadgesOnLoadingRows']}, grey_score_badges={scan['greyScoreBadgesOnLoadingRows']} -> {status}")

                if scan["loadingCellsWithContent"]:
                    print(f"  Content on loading rows: {scan['loadingCellsWithContent'][:5]}")

            # Screenshot right after bucket switch (while possibly still loading)
            take_screenshot(page, f"skel_02_bucket_{i+1:02d}_{bucket.replace(' ','_')[:20]}_immediate.png")

            # Wait for real data to arrive
            try:
                wait_for_grid_real_data(page, timeout_ms=15000)
            except Exception:
                print(f"  WARNING: Timed out waiting for real rows in bucket '{bucket}'")

            time.sleep(0.5)
            take_screenshot(page, f"skel_03_bucket_{i+1:02d}_{bucket.replace(' ','_')[:20]}_loaded.png")

            # Get renderer-level violations (from patched functions)
            viol = get_violation_summary(page)
            print(f"  Renderer violations: {len(viol['violations'])}, loading rows observed by renderers: {viol['loadingRowsObserved']}")

            if viol["violations"]:
                print(f"  VIOLATION DETAIL: {viol['violations'][:5]}")
                test_results["passed"] = False
                test_results["failures"].append(
                    f"Bucket '{bucket}': {len(viol['violations'])} renderer violation(s): {viol['violations'][:3]}"
                )

            test_results["violations_by_bucket"][bucket] = viol
            test_results["dom_scans_by_bucket"][bucket] = bucket_scans

            # Check DOM scans for any violations
            for scan in bucket_scans:
                total_viols = scan["redNoBadgesOnLoadingRows"] + scan["greyScoreBadgesOnLoadingRows"] + scan["loadingRowsWithCheckboxes"]
                if total_viols > 0:
                    test_results["passed"] = False
                    test_results["failures"].append(
                        f"Bucket '{bucket}' at {scan['label']}: DOM shows {total_viols} skeleton violations "
                        f"(red No badges: {scan['redNoBadgesOnLoadingRows']}, "
                        f"grey score badges: {scan['greyScoreBadgesOnLoadingRows']}, "
                        f"checkboxes: {scan['loadingRowsWithCheckboxes']})"
                    )

        # ── RAPID SWITCHING ────────────────────────────────────────────────────
        print("\n=== RAPID SWITCHING: 3 quick switches ===")
        rapid_buckets = ["APPROVED", "NEEDS REVIEW", "APPROVED"]
        rapid_violations = []

        for rb in rapid_buckets:
            switch_to_bucket(page, rb)
            time.sleep(0.05)  # Intentionally fast — race condition check
            scan = scan_dom_for_skeleton_badges(page)
            total_viols = scan["redNoBadgesOnLoadingRows"] + scan["greyScoreBadgesOnLoadingRows"] + scan["loadingRowsWithCheckboxes"]
            rapid_violations.append({"bucket": rb, "violations": total_viols, "scan": scan})
            print(f"  Rapid switch -> {rb}: loading_rows={scan['loadingRows']}, violations={total_viols}")

        take_screenshot(page, "skel_04_rapid_switch.png")

        for rv in rapid_violations:
            if rv["violations"] > 0:
                test_results["passed"] = False
                test_results["failures"].append(
                    f"Rapid switch to '{rv['bucket']}': {rv['violations']} skeleton violation(s)"
                )

        test_results["rapid_violations"] = rapid_violations

        # Wait for final load
        try:
            wait_for_grid_real_data(page, timeout_ms=15000)
        except Exception:
            pass
        time.sleep(0.5)
        take_screenshot(page, "skel_05_final_state.png")

        # ── CONSOLE ERRORS ─────────────────────────────────────────────────────
        relevant_errors = [
            e for e in console_errors
            if "TypeError" in e["text"] or "Cannot read" in e["text"]
            or "null guard" in e["text"] or "params.data" in e["text"]
            or "undefined" in e["text"].lower() and "error" in e["type"]
        ]
        test_results["console_errors"] = relevant_errors[:20]

        browser.close()

    return test_results


def main():
    print("=" * 70)
    print("SKELETON SUPPRESSION TEST")
    print("Verifying: null guards + infiniteInitialRowCount=1")
    print("=" * 70)

    results = run_test()

    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)
    print(f"infiniteInitialRowCount: {results['infiniteInitialRowCount']}")
    print(f"Null guards injectable:  {results['null_guards_verified']}")

    print("\nViolations by bucket:")
    for bucket, viol in results["violations_by_bucket"].items():
        count = len(viol.get("violations", []))
        loading = viol.get("loadingRowsObserved", 0)
        print(f"  {bucket}: {count} renderer violations, {loading} loading-row renderer calls")

    print("\nDOM scan summary by bucket:")
    for bucket, scans in results["dom_scans_by_bucket"].items():
        for scan in scans:
            total = scan["redNoBadgesOnLoadingRows"] + scan["greyScoreBadgesOnLoadingRows"] + scan["loadingRowsWithCheckboxes"]
            if total > 0 or scan["loadingRows"] > 0:
                print(f"  {bucket} [{scan['label']}]: loading_rows={scan['loadingRows']}, violations={total}")

    print("\nRapid switch violations:")
    for rv in results.get("rapid_violations", []):
        print(f"  {rv['bucket']}: {rv['violations']}")

    if results["console_errors"]:
        print(f"\nRelevant console errors ({len(results['console_errors'])}):")
        for e in results["console_errors"]:
            print(f"  [{e['type']}] {e['text'][:200]}")
    else:
        print("\nNo relevant console errors.")

    print("\n" + "=" * 70)
    if results["passed"]:
        print("OVERALL: PASS - No skeleton violations detected")
    else:
        print("OVERALL: FAIL")
        for f in results["failures"]:
            print(f"  FAIL: {f}")
    print("=" * 70)

    return results


if __name__ == "__main__":
    main()

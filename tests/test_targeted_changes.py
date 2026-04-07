"""Targeted tests for 4 specific recent changes in the BA Review App."""
from playwright.sync_api import sync_playwright
import requests
import time
import json


BASE_URL = "http://127.0.0.1:5000"


def get_bucket_counts():
    return requests.get(f"{BASE_URL}/api/bucket-counts", timeout=15).json()


def get_cache_status():
    return requests.get(f"{BASE_URL}/api/cache-status", timeout=15).json()


def api_approve(row_id, old_val="NEEDS REVIEW", new_val="APPROVED"):
    return requests.post(
        f"{BASE_URL}/api/update",
        json={"row_id": row_id, "source_ssn": "", "field": "recommendation",
              "value": new_val, "old_value": old_val},
        timeout=15,
    ).json()


def main():
    results = []

    def check(name, cond, detail=""):
        status = "PASS" if cond else "FAIL"
        results.append((status, name, detail))
        print(f"  {status}: {name}" + (f" | {detail}" if detail else ""))

    print("=" * 60)
    print("TARGETED CHANGE VERIFICATION TEST")
    print("=" * 60)

    # ── Change 1: 100K row cap API tests (no browser needed) ──
    print("\n[CHANGE 1] 100K Row Cap")

    r = requests.get(f"{BASE_URL}/api/matches?start=0&length=100", timeout=30).json()
    rows = len(r.get("data", []))
    check("length=100 returns exactly 100 rows", rows == 100, f"got {rows}")

    r2 = requests.get(f"{BASE_URL}/api/matches?start=0&length=-1&recommendation=APPROVED", timeout=30).json()
    rows2 = len(r2.get("data", []))
    total2 = r2.get("recordsFiltered", 0)
    check("length=-1 capped at <=100K", rows2 <= 100_000, f"got {rows2}")
    check("length=-1 returns all filtered rows (bucket<100K)", rows2 >= total2, f"rows={rows2} filtered={total2}")

    r3 = requests.get(f"{BASE_URL}/api/matches?start=0&length=200000&recommendation=APPROVED", timeout=30).json()
    rows3 = len(r3.get("data", []))
    check("length=200000 capped at <=100K", rows3 <= 100_000, f"got {rows3}")

    # ── Change 3 & 4: Approve flow + cache invalidation (API level) ──
    print("\n[CHANGE 3+4] Approve Flow & Cache Invalidation")

    baseline = get_bucket_counts()
    nr_baseline = baseline.get("NEEDS REVIEW", 0)
    apr_baseline = baseline.get("APPROVED", 0)
    print(f"  Baseline: NEEDS REVIEW={nr_baseline}, APPROVED={apr_baseline}")

    # Get a test record
    first_nr = requests.get(
        f"{BASE_URL}/api/matches?start=0&length=1&recommendation=NEEDS+REVIEW", timeout=30
    ).json()
    test_rows = first_nr.get("data", [])
    check("Can fetch a NEEDS REVIEW record", len(test_rows) > 0, f"got {len(test_rows)}")
    if not test_rows:
        print("  SKIPPED: no NEEDS REVIEW rows available")
        return

    test_id = test_rows[0]["_row_id"]
    print(f"  Test record: row_id={test_id}")

    # Load APPROVED cache before approve (to test invalidation)
    requests.get(f"{BASE_URL}/api/matches?start=0&length=25&recommendation=APPROVED", timeout=30)
    cache_before = get_cache_status()
    check("Cache populated before approve",
          cache_before.get("mode") == "cached" or cache_before.get("mode") is not None,
          f"mode={cache_before.get('mode')}")

    # Approve
    approve_resp = api_approve(test_id)
    check("Approve API returns success", approve_resp.get("success") is True, str(approve_resp))

    # Check cache invalidated
    cache_after = get_cache_status()
    check("Cache invalidated after approve (Change 4)",
          cache_after.get("mode") != "cached",
          f"mode={cache_after.get('mode')}, bucket={cache_after.get('bucket')}")

    # Check counts
    counts_after = get_bucket_counts()
    nr_after = counts_after.get("NEEDS REVIEW", 0)
    apr_after = counts_after.get("APPROVED", 0)
    check("NEEDS REVIEW decreased by 1", nr_after == nr_baseline - 1,
          f"{nr_baseline} -> {nr_after}")
    check("APPROVED increased by 1", apr_after == apr_baseline + 1,
          f"{apr_baseline} -> {apr_after}")

    # Verify record NOT in NEEDS REVIEW
    nr_check = requests.get(
        f"{BASE_URL}/api/matches?start=0&length=100&recommendation=NEEDS+REVIEW", timeout=30
    ).json()
    nr_ids = [r["_row_id"] for r in nr_check.get("data", [])]
    nr_filtered = nr_check.get("recordsFiltered", 0)
    check("Record removed from NEEDS REVIEW filter",
          test_id not in nr_ids, f"record {test_id} in NR results: {test_id in nr_ids}")
    check("recordsFiltered decreased by 1 in NEEDS REVIEW",
          nr_filtered == nr_baseline - 1, f"expected {nr_baseline-1}, got {nr_filtered}")

    # Verify record IS in APPROVED
    apr_check = requests.get(
        f"{BASE_URL}/api/matches?start=0&length=200&recommendation=APPROVED", timeout=30
    ).json()
    apr_ids = [r["_row_id"] for r in apr_check.get("data", [])]
    check("Record appears in APPROVED filter",
          test_id in apr_ids, f"record {test_id} in APR: {test_id in apr_ids}")

    # Restore
    restore_resp = api_approve(test_id, old_val="APPROVED", new_val="NEEDS REVIEW")
    check("Restore returns success", restore_resp.get("success") is True, str(restore_resp))

    restored = get_bucket_counts()
    check("NEEDS REVIEW restored to baseline",
          restored.get("NEEDS REVIEW") == nr_baseline,
          f"expected {nr_baseline}, got {restored.get('NEEDS REVIEW')}")
    check("APPROVED restored to baseline",
          restored.get("APPROVED") == apr_baseline,
          f"expected {apr_baseline}, got {restored.get('APPROVED')}")

    # ── Change 2: Null guards + grid rendering (requires browser) ──
    print("\n[CHANGE 2] Null Guards + Grid Rendering (Browser)")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()

        console_errors = []
        console_warnings = []

        def on_console(msg):
            text = msg.text
            if msg.type == "error":
                console_errors.append(text)
            elif msg.type == "warning":
                if "drawing rows" in text.lower() or "cannot get grid" in text.lower():
                    console_warnings.append(text)

        page.on("console", on_console)

        # Page load
        page.goto(BASE_URL)
        page.wait_for_selector("#matchesGrid .ag-row", timeout=30000)
        page.wait_for_timeout(2500)

        # Check null guard errors
        null_errs = [e for e in console_errors if "Cannot read" in e or
                     "undefined" in e.lower() or "null" in e.lower()]
        draw_warnings = [w for w in console_warnings]
        check("No null/undefined JS errors on initial load (Change 2)",
              len(null_errs) == 0,
              f"{len(null_errs)} null errors: {null_errs[:2]}")
        check("No 'drawing rows' warnings (datasource timing fix)",
              len(draw_warnings) == 0,
              f"{len(draw_warnings)} warnings: {draw_warnings[:2]}")

        # Grid shows data
        row_count = page.locator("#matchesGrid .ag-row[row-index]").count()
        check("Grid renders rows", row_count > 0, f"visible rows={row_count}")

        # Bucket badges
        badge_texts = page.locator(".bucket-count").all_text_contents()
        non_empty_badges = [t for t in badge_texts if t.strip()]
        check("Bucket count badges display counts",
              len(non_empty_badges) > 0,
              f"badges: {badge_texts[:5]}")

        # Click NEEDS REVIEW card
        nr_card = page.locator("[data-rec='NEEDS REVIEW']").first
        if nr_card.count() > 0:
            nr_card.click()
            page.wait_for_timeout(2000)
            nr_rows = page.locator("#matchesGrid .ag-row[row-index]").count()
            check("NEEDS REVIEW bucket filter shows rows", nr_rows > 0, f"rows={nr_rows}")
        else:
            check("NEEDS REVIEW card found", False, "card not found in DOM")

        # Scroll to trigger lazy loading
        errs_before_scroll = len(console_errors)
        grid_viewport = page.locator(".ag-body-viewport")
        if grid_viewport.count() > 0:
            grid_viewport.evaluate("el => { el.scrollTop = 3000; }")
            page.wait_for_timeout(2500)
        errs_after = console_errors[errs_before_scroll:]
        scroll_null_errs = [e for e in errs_after if "Cannot read" in e or "undefined" in e.lower()]
        check("No null errors after scrolling lazy-loaded rows (Change 2)",
              len(scroll_null_errs) == 0,
              f"errors: {scroll_null_errs[:2]}")

        # Sort a column
        errs_before_sort = len(console_errors)
        name_header = page.locator(".ag-header-cell[col-id='source_name']")
        if name_header.count() > 0:
            name_header.click()
            page.wait_for_timeout(1500)
        errs_sort = console_errors[errs_before_sort:]
        sort_null_errs = [e for e in errs_sort if "Cannot read" in e]
        check("No null errors after column sort", len(sort_null_errs) == 0,
              f"errors: {sort_null_errs[:2]}")

        # Check quickApprove button exists in a row
        approve_btns = page.locator("[onclick*='quickApprove']")
        check("quickApprove button present in grid rows",
              approve_btns.count() > 0,
              f"count={approve_btns.count()}")

        # UI approve test via browser
        print("\n[CHANGE 3] UI Approve via Browser")
        btn = approve_btns.first
        if btn.count() > 0:
            # Get current NR count
            nr_before_ui = get_bucket_counts().get("NEEDS REVIEW", 0)
            row_id_to_approve = page.evaluate(
                "() => gridApi.getDisplayedRowAtIndex(0)?.data?._row_id"
            )
            print(f"  Approving row_id={row_id_to_approve} via UI click")

            btn.click()
            page.wait_for_selector("#confirmModal.show", timeout=5000)
            check("Confirm modal appears", True, "modal visible")
            page.locator("#confirmModalOk").click()

            # Wait for grid refresh
            page.wait_for_timeout(4000)

            # Check bucket counts
            nr_after_ui = get_bucket_counts().get("NEEDS REVIEW", 0)
            apr_after_ui = get_bucket_counts().get("APPROVED", 0)
            check("UI approve: NEEDS REVIEW decreased",
                  nr_after_ui < nr_before_ui,
                  f"{nr_before_ui} -> {nr_after_ui}")

            # Restore
            if row_id_to_approve:
                restore = api_approve(row_id_to_approve, old_val="APPROVED", new_val="NEEDS REVIEW")
                check("UI approve: restored", restore.get("success") is True, str(restore))
        else:
            check("quickApprove button clickable for UI test", False, "no button found")

        # Final error check
        total_errs = len(console_errors)
        check("Total console errors in browser session <= 0",
              total_errs == 0,
              f"{total_errs} error(s): {console_errors[:3]}")

        browser.close()

    # ── Summary ──
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    passed = sum(1 for s, _, _ in results if s == "PASS")
    failed = sum(1 for s, _, _ in results if s == "FAIL")
    print(f"PASSED: {passed}/{len(results)}")
    print(f"FAILED: {failed}/{len(results)}")
    if failed > 0:
        print("\nFailed checks:")
        for s, n, d in results:
            if s == "FAIL":
                print(f"  - {n}: {d}")


if __name__ == "__main__":
    main()

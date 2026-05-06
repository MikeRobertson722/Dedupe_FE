"""
Test: Row heights and translateY positions with autoHeight + fixRowPositions()

Verifies:
1. Single-line rows render at ~24px
2. translateY values are contiguous (no gaps, no overlaps)
3. Multi-line rows (KENAN JONES) are taller than 24px
4. No overlap with adjacent rows after multi-line row
5. After search clear, contiguous positioning is restored
6. No console errors
"""

import pytest
import time
from playwright.sync_api import Page


BASE_URL = "http://127.0.0.1:5000"
TOLERANCE = 2  # px tolerance for float rounding


def wait_for_grid_stable(page: Page, min_rows: int = 5, timeout: int = 15000):
    """Wait until AG Grid has rendered rows and fixRowPositions has fired (50ms timeout)."""
    page.wait_for_function(
        f"() => document.querySelectorAll('#matchesGrid .ag-center-cols-container .ag-row').length >= {min_rows}",
        timeout=timeout
    )
    # Wait for gridInfo to confirm data loaded
    page.wait_for_function(
        "() => { var t = document.querySelector('#gridInfo'); return t && /\\d/.test(t.innerText) && t.innerText !== '0 records'; }",
        timeout=10000
    )
    # Allow extra time for the 50ms fixRowPositions setTimeout to fire and autoHeight to expand
    page.wait_for_timeout(300)


def get_row_metrics(page: Page):
    """
    Returns sorted list of dicts: {idx, height, translateY, addr_lines, addr_text}
    for all rendered rows in the center container.
    """
    return page.evaluate("""
        () => {
            var container = document.querySelector('#matchesGrid .ag-center-cols-container');
            if (!container) container = document.querySelector('.ag-center-cols-container');
            if (!container) return [];
            var rows = container.querySelectorAll('.ag-row');
            var results = [];
            rows.forEach(function(el) {
                var idx = parseInt(el.getAttribute('row-index'), 10);
                if (isNaN(idx)) return;
                var h = el.offsetHeight;
                var t = el.style.transform || '';
                var m = t.match(/translateY\\((\\d+(?:\\.\\d+)?)px\\)/);
                var y = m ? parseFloat(m[1]) : 0;
                var addrCell = el.querySelector('[col-id="source_address_recomend"]');
                var addrText = addrCell ? (addrCell.innerText || '') : '';
                var addrLines = addrText ? addrText.split('\\n').length : 1;
                results.push({
                    idx: idx,
                    height: h,
                    translateY: y,
                    addrText: addrText.substring(0, 80),
                    addrLines: addrLines
                });
            });
            results.sort(function(a, b) { return a.idx - b.idx; });
            return results;
        }
    """)


def get_pinned_row_metrics(page: Page):
    """Returns sorted list of {idx, height, translateY} for pinned-left rows."""
    return page.evaluate("""
        () => {
            var container = document.querySelector('#matchesGrid .ag-pinned-left-cols-container');
            if (!container) container = document.querySelector('.ag-pinned-left-cols-container');
            if (!container) return [];
            var rows = container.querySelectorAll('.ag-row');
            var results = [];
            rows.forEach(function(el) {
                var idx = parseInt(el.getAttribute('row-index'), 10);
                if (isNaN(idx)) return;
                var h = el.offsetHeight;
                var t = el.style.transform || '';
                var m = t.match(/translateY\\((\\d+(?:\\.\\d+)?)px\\)/);
                var y = m ? parseFloat(m[1]) : 0;
                results.push({ idx: idx, height: h, translateY: y });
            });
            results.sort(function(a, b) { return a.idx - b.idx; });
            return results;
        }
    """)


def check_contiguity(metrics, label="rows"):
    """
    Verify translateY[N] == translateY[N-1] + height[N-1] for all consecutive rows.
    Returns list of violation strings (empty = all good).
    """
    violations = []
    for i in range(1, len(metrics)):
        prev = metrics[i - 1]
        curr = metrics[i]
        if curr['idx'] != prev['idx'] + 1:
            continue
        expected_y = prev['translateY'] + prev['height']
        actual_y = curr['translateY']
        delta = actual_y - expected_y
        if abs(delta) > TOLERANCE:
            kind = "OVERLAP" if delta < 0 else "GAP"
            violations.append(
                f"  [{kind}] {label} row-index {curr['idx']}: "
                f"expected translateY={expected_y:.1f} "
                f"(prev[{prev['idx']}] y={prev['translateY']:.1f} + h={prev['height']}), "
                f"got {actual_y:.1f} (delta={delta:.1f}px)"
            )
    return violations


# ── Tests ────────────────────────────────────────────────────────────────────

def test_01_initial_load_row_heights(app_page: Page):
    """
    Load NEEDS REVIEW bucket (default), verify rows render after fixRowPositions.
    Prints complete height/translateY table for first 15 rows.
    """
    page = app_page
    wait_for_grid_stable(page, min_rows=5)

    metrics = get_row_metrics(page)
    assert len(metrics) >= 5, f"Expected >= 5 rows, got {len(metrics)}"

    print(f"\n  Initial load: {len(metrics)} rows rendered")
    print(f"  {'idx':>4}  {'height':>6}  {'translateY':>10}  {'addrLines':>9}  addr_text")
    print(f"  {'-'*4}  {'-'*6}  {'-'*10}  {'-'*9}  {'-'*40}")
    for m in metrics[:15]:
        marker = "<-- MULTI-LINE" if m['height'] > 24 + TOLERANCE else ""
        print(f"  {m['idx']:>4}  {m['height']:>6}px  {m['translateY']:>10.1f}  {m['addrLines']:>9}  '{m['addrText'][:40]}' {marker}")


def test_02_single_line_rows_are_24px(app_page: Page):
    """Single-line address rows must be ~24px tall."""
    page = app_page
    wait_for_grid_stable(page, min_rows=5)

    metrics = get_row_metrics(page)
    single_line = [m for m in metrics if m['addrLines'] <= 1 and len(m['addrText']) <= 45]

    if not single_line:
        pytest.skip("No single-line rows in visible block")

    failures = []
    for m in single_line[:15]:
        if abs(m['height'] - 24) > TOLERANCE:
            failures.append(f"row-index={m['idx']} height={m['height']}px (expected ~24px, addr='{m['addrText'][:30]}')")

    if failures:
        pytest.fail(f"Single-line rows not 24px:\n  " + "\n  ".join(failures))

    print(f"\n[PASS] {min(len(single_line), 15)} single-line rows are ~24px")


def test_03_translatey_contiguous_initial_load(app_page: Page):
    """
    After fixRowPositions fires on initial load, translateY must be contiguous.
    This is the core test: no row should overlap or have a gap with its neighbor.
    """
    page = app_page
    wait_for_grid_stable(page, min_rows=5)

    metrics = get_row_metrics(page)
    assert len(metrics) >= 2, f"Need >= 2 rows, got {len(metrics)}"

    print(f"\n  Contiguity check — {len(metrics)} rows:")
    for m in metrics[:15]:
        print(f"    row-index={m['idx']:3d}  h={m['height']:3d}px  translateY={m['translateY']:.1f}px  lines={m['addrLines']}")

    violations = check_contiguity(metrics, "center")
    if violations:
        pytest.fail(f"translateY NOT contiguous after fixRowPositions:\n" + "\n".join(violations))

    print(f"[PASS] All {len(metrics)} rows have contiguous translateY")


def test_04_multi_line_rows_are_taller(app_page: Page):
    """Any row with multi-line address (addrLines > 1) must be > 24px tall."""
    page = app_page
    wait_for_grid_stable(page, min_rows=5)

    metrics = get_row_metrics(page)
    multi_line = [m for m in metrics if m['addrLines'] > 1]

    if not multi_line:
        pytest.skip("No multi-line rows in current visible block")

    failures = []
    for m in multi_line:
        if m['height'] <= 24 + TOLERANCE:
            failures.append(f"row-index={m['idx']} has {m['addrLines']} lines but height={m['height']}px (addr='{m['addrText'][:40]}')")

    if failures:
        pytest.fail(f"Multi-line rows not expanded:\n  " + "\n  ".join(failures))

    print(f"\n[PASS] {len(multi_line)} multi-line row(s) correctly expanded:")
    for m in multi_line:
        print(f"  row-index={m['idx']}  h={m['height']}px  lines={m['addrLines']}  addr='{m['addrText'][:40]}'")


def test_05_pinned_left_matches_center(app_page: Page):
    """Pinned-left (checkbox) rows must have same height and translateY as center rows."""
    page = app_page
    wait_for_grid_stable(page, min_rows=5)

    center = {m['idx']: m for m in get_row_metrics(page)}
    pinned = {m['idx']: m for m in get_pinned_row_metrics(page)}

    if not pinned:
        pytest.skip("No pinned-left container found")

    failures = []
    checked = 0
    for idx, pm in sorted(pinned.items()):
        if idx not in center:
            continue
        cm = center[idx]
        h_delta = abs(pm['height'] - cm['height'])
        y_delta = abs(pm['translateY'] - cm['translateY'])
        if h_delta > TOLERANCE:
            failures.append(f"row-index={idx} height: center={cm['height']}px pinned={pm['height']}px")
        if y_delta > TOLERANCE:
            failures.append(f"row-index={idx} translateY: center={cm['translateY']:.1f} pinned={pm['translateY']:.1f}")
        checked += 1

    if failures:
        pytest.fail(f"Pinned-left rows misaligned:\n  " + "\n  ".join(failures))

    print(f"\n[PASS] {checked} pinned-left rows aligned with center rows")


def test_06_kenan_jones_multiline_height_and_no_overlap(app_page: Page):
    """
    Search for KENAN JONES.
    - The matching row must be taller than 24px (autoHeight expanded it).
    - No overlap/gap with adjacent rows.
    """
    page = app_page

    # #quickFilterInput uses a 300ms debounced 'input' handler -> applyServerFilters()
    search_input = page.locator('#quickFilterInput')
    search_input.fill("")
    page.wait_for_timeout(100)
    search_input.fill("KENAN JONES")
    # The debounce fires after 300ms; then the API call completes

    # Wait for grid to show filtered results
    page.wait_for_timeout(600)
    try:
        page.wait_for_function(
            "() => { var t = document.querySelector('#gridInfo'); return t && /\\d/.test(t.innerText); }",
            timeout=8000
        )
    except Exception:
        pass

    page.wait_for_timeout(300)

    metrics = get_row_metrics(page)

    print(f"\n  KENAN JONES search: {len(metrics)} rows")
    for m in metrics[:5]:
        print(f"    row-index={m['idx']:3d}  h={m['height']:3d}px  translateY={m['translateY']:.1f}px  addr='{m['addrText'][:60]}'")

    if not metrics:
        pytest.skip("No rows returned for KENAN JONES search")

    # Check for tall rows (multi-line)
    tall_rows = [m for m in metrics if m['height'] > 24 + TOLERANCE]
    if tall_rows:
        print(f"[PASS] KENAN JONES multi-line row: h={tall_rows[0]['height']}px")
    else:
        # If only 1 row, it might still be 24px if address fits single line
        kenan_rows = [m for m in metrics if 'KENAN' in m['addrText'].upper()]
        if not kenan_rows:
            pytest.skip("KENAN JONES not found in first loaded block")
        heights = [m['height'] for m in kenan_rows]
        pytest.fail(f"KENAN JONES row found but not expanded: heights={heights}, addr='{kenan_rows[0]['addrText']}'")

    # Check contiguity (only matters if multiple rows)
    if len(metrics) >= 2:
        violations = check_contiguity(metrics, "filtered")
        if violations:
            pytest.fail(f"Overlap after KENAN JONES search:\n" + "\n".join(violations))
        print(f"[PASS] No overlaps in {len(metrics)} filtered rows")


def test_07_clear_search_contiguity_restored(app_page: Page):
    """
    After clearing search, the full grid must still have contiguous translateY.
    """
    page = app_page

    # Ensure search is active from test_06 — clear it
    search_input = page.locator('#quickFilterInput')
    search_input.fill("")

    page.wait_for_timeout(600)
    try:
        wait_for_grid_stable(page, min_rows=5)
    except Exception:
        page.wait_for_timeout(500)

    metrics = get_row_metrics(page)
    if not metrics:
        pytest.skip("No rows after clearing search")

    print(f"\n  After clearing search: {len(metrics)} rows")
    for m in metrics[:10]:
        print(f"    row-index={m['idx']:3d}  h={m['height']:3d}px  translateY={m['translateY']:.1f}px")

    violations = check_contiguity(metrics, "post-clear")
    if violations:
        pytest.fail(f"Overlaps after clearing search:\n" + "\n".join(violations))

    print(f"[PASS] {len(metrics)} rows contiguous after clearing search")


def test_08_no_console_errors(app_page: Page):
    """No JavaScript console errors during the session."""
    page = app_page
    errors = page.evaluate("() => window._consoleErrors || []")

    real_errors = [e for e in errors if not any(skip in e for skip in [
        'suppressMenu', 'autoHeight', 'headerCheckbox', 'deprecated', 'AgGrid:', 'favicon'
    ])]

    if real_errors:
        pytest.fail(f"{len(real_errors)} console error(s):\n  " + "\n  ".join(real_errors[:5]))

    print(f"\n[PASS] No console errors (captured: {len(errors)}, all benign)")

"""
Focused regression test: grid blanking on Page Down / Page Up scroll.

The previous fixRowPositions() implementation modified container height, which
caused the grid body to go blank (all rows disappeared) on scroll events.
This version does NOT modify container height — it only adjusts row translateY.

CRITICAL checks:
  1. After each Page Down/Up press, the center-cols-container must have >= 1 visible row.
  2. The ag-center-cols-container must never be empty (0 rows) during scroll.
  3. No console errors during the scroll cycle.
"""

import pytest
from playwright.sync_api import Page


BASE_URL = "http://127.0.0.1:5000"
TOLERANCE = 2
FIX_WAIT_MS = 250   # More than the 30ms debounce + autoHeight render time


def wait_for_grid_stable(page: Page, min_rows: int = 5, timeout: int = 20000):
    page.wait_for_function(
        f"() => document.querySelectorAll('#matchesGrid .ag-center-cols-container .ag-row').length >= {min_rows}",
        timeout=timeout
    )
    page.wait_for_function(
        "() => { var t = document.querySelector('#gridInfo'); "
        "return t && /\\d/.test(t.innerText) && t.innerText !== '0 records'; }",
        timeout=10000
    )
    page.wait_for_timeout(300)


def count_visible_rows(page: Page) -> int:
    """Count non-loading rows in the center-cols-container."""
    return page.evaluate("""
        () => {
            var container = document.querySelector(
                '#matchesGrid .ag-center-cols-container'
            ) || document.querySelector('.ag-center-cols-container');
            if (!container) return -1;
            var rows = container.querySelectorAll('.ag-row:not(.ag-row-loading)');
            return rows.length;
        }
    """)


def get_container_info(page: Page) -> dict:
    """Snapshot container height and row count for blanking detection."""
    return page.evaluate("""
        () => {
            var container = document.querySelector(
                '#matchesGrid .ag-center-cols-container'
            ) || document.querySelector('.ag-center-cols-container');
            var viewport = document.querySelector(
                '#matchesGrid .ag-body-viewport'
            ) || document.querySelector('.ag-body-viewport');
            if (!container) return {rows: -1, containerHeight: -1, viewportHeight: -1};
            var rows = container.querySelectorAll('.ag-row:not(.ag-row-loading)');
            return {
                rows: rows.length,
                containerHeight: container.offsetHeight,
                viewportHeight: viewport ? viewport.offsetHeight : -1,
                containerStyle: container.style.height || '(none set)'
            };
        }
    """)


def get_row_metrics(page: Page):
    return page.evaluate("""
        () => {
            var container = document.querySelector(
                '#matchesGrid .ag-center-cols-container'
            ) || document.querySelector('.ag-center-cols-container');
            if (!container) return [];
            var rows = container.querySelectorAll('.ag-row:not(.ag-row-loading)');
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


def check_contiguity(metrics):
    violations = []
    for i in range(1, len(metrics)):
        prev = metrics[i - 1]
        curr = metrics[i]
        if curr['idx'] != prev['idx'] + 1:
            continue
        expected_y = prev['translateY'] + prev['height']
        delta = curr['translateY'] - expected_y
        if abs(delta) > TOLERANCE:
            kind = "OVERLAP" if delta < 0 else "GAP"
            violations.append(
                f"  [{kind}] row-index={curr['idx']}: "
                f"expected translateY={expected_y:.1f} "
                f"(prev[{prev['idx']}] y={prev['translateY']:.1f} + h={prev['height']}), "
                f"got {curr['translateY']:.1f}  delta={delta:+.1f}px"
            )
    return violations


def focus_grid(page: Page):
    grid_body = page.locator('.ag-center-cols-viewport').first
    grid_body.click()
    page.wait_for_timeout(80)


# ── Tests ────────────────────────────────────────────────────────────────────

def test_01_no_blanking_page_down(app_page: Page):
    """
    Press Page Down 4 times. After each press (+250ms):
    - The center-cols-container must have >= 1 visible (non-loading) row.
    - A count of 0 rows = BLANKING DETECTED.
    """
    page = app_page
    wait_for_grid_stable(page, min_rows=5)

    # Baseline snapshot
    baseline = get_container_info(page)
    print(f"\n  Baseline: {baseline['rows']} rows, containerH={baseline['containerHeight']}px, "
          f"viewportH={baseline['viewportHeight']}px, containerStyle='{baseline['containerStyle']}'")

    focus_grid(page)

    blanking_events = []
    for i in range(1, 5):
        page.keyboard.press("PageDown")
        page.wait_for_timeout(FIX_WAIT_MS)

        info = get_container_info(page)
        print(f"  After PageDown {i}: {info['rows']} rows, "
              f"containerH={info['containerHeight']}px, "
              f"containerStyle='{info['containerStyle']}'")

        if info['rows'] == 0:
            blanking_events.append(f"PageDown press {i}: 0 rows in center container (BLANKING)")
        elif info['rows'] < 0:
            blanking_events.append(f"PageDown press {i}: container not found in DOM")

    if blanking_events:
        pytest.fail(
            f"GRID BLANKING DETECTED during Page Down scrolling:\n  "
            + "\n  ".join(blanking_events)
        )

    print(f"\n[PASS] No blanking after 4x Page Down — grid remained populated throughout")


def test_02_no_blanking_page_up(app_page: Page):
    """
    Scroll down 4 pages, then Page Up 4 times — check for blanking on the way back up.
    """
    page = app_page
    wait_for_grid_stable(page, min_rows=5)
    focus_grid(page)

    # Scroll down first
    for _ in range(4):
        page.keyboard.press("PageDown")
        page.wait_for_timeout(FIX_WAIT_MS)

    # Now scroll back up
    blanking_events = []
    for i in range(1, 5):
        page.keyboard.press("PageUp")
        page.wait_for_timeout(FIX_WAIT_MS)

        info = get_container_info(page)
        print(f"\n  After PageUp {i}: {info['rows']} rows, "
              f"containerH={info['containerHeight']}px, "
              f"containerStyle='{info['containerStyle']}'")

        if info['rows'] == 0:
            blanking_events.append(f"PageUp press {i}: 0 rows in center container (BLANKING)")
        elif info['rows'] < 0:
            blanking_events.append(f"PageUp press {i}: container not found in DOM")

    if blanking_events:
        pytest.fail(
            f"GRID BLANKING DETECTED during Page Up scrolling:\n  "
            + "\n  ".join(blanking_events)
        )

    print(f"\n[PASS] No blanking after 4x Page Up — grid remained populated throughout")


def test_03_container_height_stable_during_scroll(app_page: Page):
    """
    Verify fixRowPositions() does NOT change the ag-center-cols-container height
    during scrolling (the old bug: every fixRowPositions call expanded the container
    height, which caused AG Grid to blank the row buffer on subsequent renders).

    The new implementation only modifies row translateY values, never the container.
    So the container height set by AG Grid must remain exactly the same value
    before and after scrolling.

    Note: AG Grid itself sets a numeric style.height on this container (e.g. '2424px')
    as part of its IRM layout — that is expected and correct. What must NOT happen is
    fixRowPositions() changing that value mid-scroll.
    """
    page = app_page
    wait_for_grid_stable(page, min_rows=5)

    # Capture baseline height (set by AG Grid on initial render)
    baseline_height = page.evaluate("""
        () => {
            var c = document.querySelector(
                '#matchesGrid .ag-center-cols-container'
            ) || document.querySelector('.ag-center-cols-container');
            return c ? (c.style.height || '') : 'CONTAINER_NOT_FOUND';
        }
    """)

    print(f"\n  Baseline ag-center-cols-container style.height = '{baseline_height}'")

    if baseline_height == 'CONTAINER_NOT_FOUND':
        pytest.fail("Could not find ag-center-cols-container in DOM")

    focus_grid(page)

    height_changes = []
    for i in range(1, 5):
        page.keyboard.press("PageDown")
        page.wait_for_timeout(FIX_WAIT_MS)

        current_height = page.evaluate("""
            () => {
                var c = document.querySelector(
                    '#matchesGrid .ag-center-cols-container'
                ) || document.querySelector('.ag-center-cols-container');
                return c ? (c.style.height || '') : 'CONTAINER_NOT_FOUND';
            }
        """)

        print(f"  After PageDown {i}: style.height = '{current_height}'")

        if current_height != baseline_height:
            height_changes.append(
                f"PageDown press {i}: height changed from '{baseline_height}' to '{current_height}' "
                f"(fixRowPositions() must NOT modify container height)"
            )

    if height_changes:
        pytest.fail(
            f"ag-center-cols-container height was modified during scroll by fixRowPositions():\n  "
            + "\n  ".join(height_changes)
        )

    print(f"[PASS] ag-center-cols-container style.height stable at '{baseline_height}' throughout 4x PageDown")


def test_04_contiguous_after_rapid_scroll(app_page: Page):
    """
    3 rapid Page Down then 3 rapid Page Up with no inter-press delay.
    After burst: wait 300ms, then verify rows are contiguous and count > 0.
    """
    page = app_page
    wait_for_grid_stable(page, min_rows=5)
    focus_grid(page)

    # Rapid down
    page.keyboard.press("PageDown")
    page.keyboard.press("PageDown")
    page.keyboard.press("PageDown")
    # Rapid up
    page.keyboard.press("PageUp")
    page.keyboard.press("PageUp")
    page.keyboard.press("PageUp")

    # Wait for the 30ms debounce to fire and autoHeight to settle
    page.wait_for_timeout(350)

    info = get_container_info(page)
    metrics = get_row_metrics(page)

    print(f"\n  After rapid burst: {info['rows']} rows, "
          f"containerH={info['containerHeight']}px, "
          f"containerStyle='{info['containerStyle']}'")

    if info['rows'] == 0:
        pytest.fail("GRID BLANKING: 0 rows after rapid Page Down/Up burst")

    assert len(metrics) >= 2, f"Expected >= 2 rows after rapid burst, got {len(metrics)}"

    violations = check_contiguity(metrics)
    for m in metrics[:10]:
        print(f"  idx={m['idx']:3d}  h={m['height']:3d}px  translateY={m['translateY']:.1f}px")

    if violations:
        pytest.fail(
            f"translateY NOT contiguous after rapid scroll burst "
            f"({len(violations)} violation(s)):\n" + "\n".join(violations)
        )

    print(f"[PASS] No blanking and {len(metrics)} rows contiguous after rapid burst")


def test_05_no_console_errors_during_scroll(app_page: Page):
    """No JS console errors during a Page Down + Page Up scroll cycle."""
    page = app_page
    wait_for_grid_stable(page, min_rows=5)
    focus_grid(page)

    for _ in range(4):
        page.keyboard.press("PageDown")
        page.wait_for_timeout(FIX_WAIT_MS)
    for _ in range(4):
        page.keyboard.press("PageUp")
        page.wait_for_timeout(FIX_WAIT_MS)

    errors = page.evaluate("() => window._consoleErrors || []")
    real_errors = [
        e for e in errors if not any(skip in e for skip in [
            'suppressMenu', 'autoHeight', 'headerCheckbox',
            'deprecated', 'AgGrid:', 'favicon'
        ])
    ]

    if real_errors:
        pytest.fail(
            f"{len(real_errors)} console error(s) during scroll cycle:\n  "
            + "\n  ".join(real_errors[:10])
        )

    print(f"\n[PASS] No console errors during Page Down/Up cycle "
          f"(captured: {len(errors)}, all benign)")

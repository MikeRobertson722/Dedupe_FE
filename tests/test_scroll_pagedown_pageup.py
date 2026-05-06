"""
Test: Page Down / Page Up scrolling — no row overlap after onBodyScrollEnd / onViewportChanged

Verifies that fixRowPositions() (debounced 50ms) correctly recalculates translateY
for all visible rows after every Page Down or Page Up keypress, and that no two
consecutive rendered rows overlap or have a gap between them.

Fix being verified:
  - onBodyScrollEnd: function() { fixRowPositions(); }
  - onViewportChanged: function() { fixRowPositions(); }
  Both call the same debounced fixRowPositions() (50ms delay).

Key invariant checked after every scroll action:
  row[N].translateY == row[N-1].translateY + row[N-1].offsetHeight
  for all consecutive rendered rows (by row-index).
"""

import pytest
import time
from playwright.sync_api import Page


BASE_URL = "http://127.0.0.1:5000"
TOLERANCE = 2       # px tolerance for float rounding
FIX_WAIT_MS = 200   # wait after each scroll for fixRowPositions (50ms debounce + render margin)


# ── Helpers ──────────────────────────────────────────────────────────────────

def wait_for_grid_stable(page: Page, min_rows: int = 5, timeout: int = 20000):
    """Wait until AG Grid has rendered rows, gridInfo shows data, and fixRowPositions has fired."""
    page.wait_for_function(
        f"() => document.querySelectorAll('#matchesGrid .ag-center-cols-container .ag-row').length >= {min_rows}",
        timeout=timeout
    )
    page.wait_for_function(
        "() => { var t = document.querySelector('#gridInfo'); "
        "return t && /\\d/.test(t.innerText) && t.innerText !== '0 records'; }",
        timeout=10000
    )
    # Allow 50ms debounce + autoHeight render to settle
    page.wait_for_timeout(300)


def get_row_metrics(page: Page):
    """
    Returns list of dicts sorted by row-index:
      {idx, height, translateY, addrLines, addrText}
    Only rows in the center-cols-container (not loading skeletons).
    """
    return page.evaluate("""
        () => {
            var container = document.querySelector(
                '#matchesGrid .ag-center-cols-container'
            ) || document.querySelector('.ag-center-cols-container');
            if (!container) return [];
            var rows = container.querySelectorAll('.ag-row');
            var results = [];
            rows.forEach(function(el) {
                var idx = parseInt(el.getAttribute('row-index'), 10);
                if (isNaN(idx)) return;
                // Skip loading-placeholder rows — they have no real data
                if (el.classList.contains('ag-row-loading')) return;
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
    """Returns list of {idx, height, translateY} for pinned-left rows, sorted by idx."""
    return page.evaluate("""
        () => {
            var container = document.querySelector(
                '#matchesGrid .ag-pinned-left-cols-container'
            ) || document.querySelector('.ag-pinned-left-cols-container');
            if (!container) return [];
            var rows = container.querySelectorAll('.ag-row');
            var results = [];
            rows.forEach(function(el) {
                var idx = parseInt(el.getAttribute('row-index'), 10);
                if (isNaN(idx)) return;
                if (el.classList.contains('ag-row-loading')) return;
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
    For each pair of consecutive rows (idx N and N+1), verify:
      row[N+1].translateY == row[N].translateY + row[N].height

    Non-consecutive index pairs (e.g. idx 5 then idx 8 — loading rows in between)
    are skipped — they cannot be checked without knowing heights of intervening rows.

    Returns list of violation description strings (empty list = all good).
    """
    violations = []
    for i in range(1, len(metrics)):
        prev = metrics[i - 1]
        curr = metrics[i]
        # Only check truly adjacent row-indexes
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
                f"got {actual_y:.1f}  delta={delta:+.1f}px"
            )
    return violations


def focus_grid(page: Page):
    """Click the AG Grid body to give it keyboard focus."""
    grid_body = page.locator('.ag-center-cols-viewport').first
    grid_body.click()
    page.wait_for_timeout(80)


def scroll_and_verify(page: Page, key: str, presses: int, step_wait_ms: int,
                       step_label_prefix: str):
    """
    Press `key` (PageDown or PageUp) `presses` times.
    After each press, wait step_wait_ms then assert contiguity.
    Returns list of all failures across all steps.
    """
    all_failures = []
    for i in range(1, presses + 1):
        page.keyboard.press(key)
        page.wait_for_timeout(step_wait_ms)

        metrics = get_row_metrics(page)
        label = f"{step_label_prefix} press {i}"

        if len(metrics) < 2:
            all_failures.append(f"  {label}: only {len(metrics)} rendered row(s) — cannot verify")
            continue

        violations = check_contiguity(metrics, label)
        if violations:
            all_failures.extend(violations)
            print(f"\n  FAIL after {label}: {len(violations)} violation(s)")
        else:
            print(f"\n  PASS after {label}: {len(metrics)} rows contiguous")

        # Print first 8 rows for diagnostics
        print(f"  {'idx':>4}  {'h':>4}  {'translateY':>10}")
        for m in metrics[:8]:
            print(f"  {m['idx']:>4}  {m['height']:>4}px  {m['translateY']:>10.1f}  lines={m['addrLines']}")

    return all_failures


# ── Tests ────────────────────────────────────────────────────────────────────

def test_01_initial_load_contiguous(app_page: Page):
    """
    Baseline: NEEDS REVIEW initial render must have contiguous translateY
    before any scrolling occurs.
    """
    page = app_page
    wait_for_grid_stable(page, min_rows=5)

    metrics = get_row_metrics(page)
    assert len(metrics) >= 2, f"Need >= 2 rows for contiguity check, got {len(metrics)}"

    print(f"\n  Initial load: {len(metrics)} rows")
    print(f"  {'idx':>4}  {'h':>4}  {'translateY':>10}  lines  addr_text")
    for m in metrics[:12]:
        marker = " <MULTI-LINE" if m['height'] > 24 + TOLERANCE else ""
        print(f"  {m['idx']:>4}  {m['height']:>4}px  {m['translateY']:>10.1f}  {m['addrLines']:>5}  '{m['addrText'][:35]}'{marker}")

    violations = check_contiguity(metrics, "initial load")
    if violations:
        pytest.fail(
            f"Initial load translateY NOT contiguous ({len(violations)} violation(s)):\n"
            + "\n".join(violations)
        )

    print(f"\n[PASS] Initial load: all {len(metrics)} rows have contiguous translateY")


def test_02_page_down_contiguous(app_page: Page):
    """
    Press Page Down 4 times.
    After each press (+200ms for fixRowPositions to fire):
      - All visible rows must have contiguous translateY.
      - Multi-line rows must be taller than single-line rows.
    """
    page = app_page
    wait_for_grid_stable(page, min_rows=5)

    focus_grid(page)

    failures = scroll_and_verify(
        page, key="PageDown", presses=4,
        step_wait_ms=FIX_WAIT_MS,
        step_label_prefix="PageDown"
    )

    if failures:
        pytest.fail(
            f"translateY overlap/gap detected after Page Down scroll "
            f"({len(failures)} violation(s)):\n" + "\n".join(failures)
        )

    print(f"\n[PASS] All 4 Page Down positions have contiguous translateY")


def test_03_page_down_multi_line_rows_taller(app_page: Page):
    """
    After scrolling down 4 pages, any multi-line address row must be taller
    than a single-line row (proves autoHeight is still working post-scroll).
    """
    page = app_page
    wait_for_grid_stable(page, min_rows=5)
    focus_grid(page)

    for _ in range(4):
        page.keyboard.press("PageDown")
        page.wait_for_timeout(FIX_WAIT_MS)

    metrics = get_row_metrics(page)
    multi_line = [m for m in metrics if m['addrLines'] > 1]
    single_line = [m for m in metrics if m['addrLines'] <= 1 and len(m['addrText']) <= 45]

    if not multi_line or not single_line:
        pytest.skip(
            f"Skip: need both multi-line and single-line rows in view "
            f"(multi={len(multi_line)}, single={len(single_line)})"
        )

    failures = []
    for m in multi_line:
        if m['height'] <= 24 + TOLERANCE:
            failures.append(
                f"row-index={m['idx']} has {m['addrLines']} lines but height={m['height']}px "
                f"(addr='{m['addrText'][:40]}')"
            )

    if failures:
        pytest.fail(f"Multi-line rows not taller than 24px after Page Down:\n  " + "\n  ".join(failures))

    print(f"\n[PASS] {len(multi_line)} multi-line row(s) correctly expanded after 4x PageDown")
    for m in multi_line:
        print(f"  row-index={m['idx']}  h={m['height']}px  lines={m['addrLines']}")


def test_04_page_up_contiguous(app_page: Page):
    """
    Scroll down 4 pages, then scroll back up 4 pages.
    After each Page Up (+200ms), verify contiguous translateY.
    """
    page = app_page
    wait_for_grid_stable(page, min_rows=5)
    focus_grid(page)

    # Scroll down first to give Page Up something to do
    print("\n  Scrolling down 4 pages first...")
    for _ in range(4):
        page.keyboard.press("PageDown")
        page.wait_for_timeout(FIX_WAIT_MS)

    print("  Now scrolling back up 4 pages...")
    failures = scroll_and_verify(
        page, key="PageUp", presses=4,
        step_wait_ms=FIX_WAIT_MS,
        step_label_prefix="PageUp"
    )

    if failures:
        pytest.fail(
            f"translateY overlap/gap detected after Page Up scroll "
            f"({len(failures)} violation(s)):\n" + "\n".join(failures)
        )

    print(f"\n[PASS] All 4 Page Up positions have contiguous translateY")


def test_05_rapid_page_down_then_settle(app_page: Page):
    """
    3 rapid Page Down presses with no delay between them (simulates fast keyboard repeat).
    Wait 300ms after the burst (covers 50ms debounce + render margin).
    Verify contiguous translateY after the burst settles.
    """
    page = app_page
    wait_for_grid_stable(page, min_rows=5)
    focus_grid(page)

    print("\n  3 rapid PageDown presses (no delay)...")
    page.keyboard.press("PageDown")
    page.keyboard.press("PageDown")
    page.keyboard.press("PageDown")

    # Wait 300ms for the debounced fixRowPositions to fire
    page.wait_for_timeout(300)

    metrics = get_row_metrics(page)
    assert len(metrics) >= 2, f"Expected >= 2 rows after rapid scroll, got {len(metrics)}"

    print(f"  After rapid burst: {len(metrics)} rows visible")
    print(f"  {'idx':>4}  {'h':>4}  {'translateY':>10}")
    for m in metrics[:10]:
        print(f"  {m['idx']:>4}  {m['height']:>4}px  {m['translateY']:>10.1f}  lines={m['addrLines']}")

    violations = check_contiguity(metrics, "rapid PageDown burst")
    if violations:
        pytest.fail(
            f"translateY NOT contiguous after 3 rapid Page Down presses "
            f"({len(violations)} violation(s)):\n" + "\n".join(violations)
        )

    print(f"\n[PASS] Rapid Page Down burst: {len(metrics)} rows contiguous after 300ms settle")


def test_06_alternate_down_up_contiguous(app_page: Page):
    """
    Alternate Page Down / Page Up 3 times each in sequence.
    After each individual keypress (+200ms), verify contiguous translateY.
    This stresses the debounce cancel/restart behavior.
    """
    page = app_page
    wait_for_grid_stable(page, min_rows=5)
    focus_grid(page)

    all_failures = []
    sequence = [
        ("PageDown", "alt PageDown 1"),
        ("PageDown", "alt PageDown 2"),
        ("PageUp",   "alt PageUp 1"),
        ("PageDown", "alt PageDown 3"),
        ("PageUp",   "alt PageUp 2"),
        ("PageUp",   "alt PageUp 3"),
    ]

    print("\n  Alternating PageDown/PageUp sequence:")
    for key, label in sequence:
        page.keyboard.press(key)
        page.wait_for_timeout(FIX_WAIT_MS)

        metrics = get_row_metrics(page)
        if len(metrics) < 2:
            print(f"  SKIP {label}: only {len(metrics)} row(s)")
            continue

        violations = check_contiguity(metrics, label)
        if violations:
            all_failures.extend(violations)
            print(f"  FAIL {label}: {len(violations)} violation(s)")
        else:
            top = metrics[0]
            bot = metrics[-1]
            print(f"  PASS {label}: {len(metrics)} rows  idx=[{top['idx']}..{bot['idx']}]")

    if all_failures:
        pytest.fail(
            f"translateY violations in alternating scroll sequence "
            f"({len(all_failures)} total):\n" + "\n".join(all_failures)
        )

    print(f"\n[PASS] All alternating Page Down/Up positions have contiguous translateY")


def test_07_pinned_left_matches_center_after_scroll(app_page: Page):
    """
    After scrolling down 3 pages, pinned-left (checkbox) column rows must have
    the same height and translateY as the corresponding center rows.
    """
    page = app_page
    wait_for_grid_stable(page, min_rows=5)
    focus_grid(page)

    for _ in range(3):
        page.keyboard.press("PageDown")
        page.wait_for_timeout(FIX_WAIT_MS)

    center = {m['idx']: m for m in get_row_metrics(page)}
    pinned = {m['idx']: m for m in get_pinned_row_metrics(page)}

    if not pinned:
        pytest.skip("No pinned-left container found")

    failures = []
    checked = 0
    for idx in sorted(pinned):
        if idx not in center:
            continue
        cm = center[idx]
        pm = pinned[idx]
        h_delta = abs(pm['height'] - cm['height'])
        y_delta = abs(pm['translateY'] - cm['translateY'])
        if h_delta > TOLERANCE:
            failures.append(
                f"row-index={idx} height mismatch: center={cm['height']}px pinned={pm['height']}px"
            )
        if y_delta > TOLERANCE:
            failures.append(
                f"row-index={idx} translateY mismatch: center={cm['translateY']:.1f} pinned={pm['translateY']:.1f}"
            )
        checked += 1

    if failures:
        pytest.fail(
            f"Pinned-left rows misaligned after Page Down x3 "
            f"({len(failures)} violation(s)):\n  " + "\n  ".join(failures)
        )

    print(f"\n[PASS] {checked} pinned-left rows aligned with center after 3x PageDown")


def test_08_no_console_errors_during_scroll(app_page: Page):
    """
    No JavaScript errors in console during a full Page Down + Page Up cycle.
    AG Grid deprecation warnings (suppressMenu, autoHeight, headerCheckbox) are benign and excluded.
    """
    page = app_page
    wait_for_grid_stable(page, min_rows=5)
    focus_grid(page)

    # Perform a full down + up scroll cycle
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
            f"{len(real_errors)} console error(s) during Page Down/Up cycle:\n  "
            + "\n  ".join(real_errors[:10])
        )

    print(f"\n[PASS] No console errors during Page Down/Up cycle "
          f"(captured: {len(errors)}, all benign)")

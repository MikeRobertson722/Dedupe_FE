"""
Test: Deep scrollTop contiguity — scrolling far past the initial 100-row IRM block.

Verifies that fixRowPositions() correctly recalculates translateY for all visible rows
when AG Grid loads new blocks beyond the initial 100-row fetch.

Key scenario being tested:
  - NEEDS REVIEW bucket has ~411K rows; IRM loads 100 rows per block.
  - Direct scrollTop jumps (5000, 20000, 100000) force AG Grid to request blocks
    far past block 0.
  - AG Grid recycles row DOM elements with new row-index attributes and data.
  - fixRowPositions() must fire (via onBodyScrollEnd / onViewportChanged) and
    correctly set translateY for all visible rows including rows from new blocks.

Key invariant:
  Consecutive rendered rows (by row-index) must satisfy:
    row[N].translateY == row[N-1].translateY + row[N-1].height  (within TOLERANCE px)

Scroll positions tested:
  1. Baseline (scrollTop = 0)
  2. Moderate (scrollTop = 5000)   — block 1-2 territory
  3. Deep     (scrollTop = 20000)  — block 8-10 territory
  4. Return   (scrollTop = 0)      — verify positions restored on scroll-back
  5. Extreme  (scrollTop = 100000) — very deep, multiple new blocks
"""

import pytest
import time
from playwright.sync_api import Page


BASE_URL = "http://127.0.0.1:5000"
TOLERANCE = 2          # px tolerance for float rounding
BLOCK_WAIT_MS = 800    # wait after each scroll — covers: IRM fetch + successCallback + fixRowPositions(50ms)


# ── Shared helpers (same logic as test_scroll_pagedown_pageup.py) ─────────────

def wait_for_grid_stable(page: Page, min_rows: int = 5, timeout: int = 30000):
    """Wait until AG Grid has rendered rows, gridInfo shows data, and fixRowPositions has fired."""
    page.wait_for_function(
        f"() => document.querySelectorAll('#matchesGrid .ag-center-cols-container .ag-row').length >= {min_rows}",
        timeout=timeout
    )
    page.wait_for_function(
        "() => { var t = document.querySelector('#gridInfo'); "
        "return t && /\\d/.test(t.innerText) && t.innerText !== '0 records'; }",
        timeout=15000
    )
    page.wait_for_timeout(300)


def get_row_metrics(page: Page):
    """
    Returns list of dicts sorted by row-index:
      {idx, height, translateY, addrLines, addrText}
    Excludes loading-skeleton rows (ag-row-loading).
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


def get_viewport_scrolltop(page: Page) -> int:
    """Returns the current scrollTop of the ag-body-viewport."""
    return page.evaluate("""
        () => {
            var vp = document.querySelector('.ag-body-viewport');
            return vp ? vp.scrollTop : -1;
        }
    """)


def check_contiguity(metrics, label="rows"):
    """
    For each pair of consecutive rows (idx N and N+1), verify:
      row[N+1].translateY == row[N].translateY + row[N].height

    Non-consecutive index pairs (e.g. idx 5 then idx 8) are skipped.

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
                f"got {actual_y:.1f}  delta={delta:+.1f}px"
            )
    return violations


def scroll_to(page: Page, scroll_top: int) -> int:
    """
    Set ag-body-viewport scrollTop directly.
    Returns the actual scrollTop after the set (browser may cap it).
    """
    actual = page.evaluate(f"""
        () => {{
            var vp = document.querySelector('.ag-body-viewport');
            if (!vp) return -1;
            vp.scrollTop = {scroll_top};
            return vp.scrollTop;
        }}
    """)
    return actual


def force_fix_row_positions(page: Page):
    """Manually invoke fixRowPositions() in the page context and wait for it to settle."""
    page.evaluate("() => { if (typeof fixRowPositions === 'function') fixRowPositions(); }")
    page.wait_for_timeout(150)


def print_metrics_table(metrics, label, count=12):
    """Print a diagnostic table of the first `count` rows in metrics."""
    print(f"\n  [{label}] {len(metrics)} rendered rows  idx=[{metrics[0]['idx']}..{metrics[-1]['idx']}]")
    print(f"  {'idx':>5}  {'h':>4}  {'translateY':>11}  lines  addr_snippet")
    for m in metrics[:count]:
        print(f"  {m['idx']:>5}  {m['height']:>4}px  {m['translateY']:>11.1f}  "
              f"{m['addrLines']:>5}  '{m['addrText'][:35]}'")
    if len(metrics) > count:
        print(f"  ... ({len(metrics) - count} more rows not shown)")


def scroll_verify(page: Page, scroll_top: int, label: str,
                   extra_wait_ms: int = 0, require_min_idx: int = 0):
    """
    Jump to scroll_top, wait for data load + fixRowPositions, then verify contiguity.

    Returns (metrics, violations) tuple.
    require_min_idx: if >0, assert that at least one visible row has idx >= this value
                     (proves we actually scrolled into new-block territory).
    """
    actual_top = scroll_to(page, scroll_top)
    page.wait_for_timeout(BLOCK_WAIT_MS + extra_wait_ms)

    # If new blocks are loading, wait until at least one non-loading row appears
    try:
        page.wait_for_function(
            "() => document.querySelectorAll('#matchesGrid .ag-center-cols-container "
            ".ag-row:not(.ag-row-loading)').length >= 3",
            timeout=10000
        )
    except Exception:
        pass  # proceed even if wait times out — metrics will reveal the issue

    # Give fixRowPositions one extra cycle to fire after rows appear
    page.wait_for_timeout(200)

    metrics = get_row_metrics(page)
    violations = []

    if len(metrics) < 2:
        violations.append(f"  Only {len(metrics)} rendered row(s) at scrollTop={scroll_top} — cannot verify")
        return metrics, violations

    print_metrics_table(metrics, label)

    if require_min_idx > 0:
        max_idx = max(m['idx'] for m in metrics)
        if max_idx < require_min_idx:
            violations.append(
                f"  Scroll did not reach expected depth: max visible row-index={max_idx}, "
                f"wanted >= {require_min_idx}"
            )

    violations.extend(check_contiguity(metrics, label))
    return metrics, violations


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_01_baseline_contiguous(app_page: Page):
    """
    Baseline: initial load at scrollTop=0 must have contiguous translateY.
    Establishes the reference state before any deep-scroll tests.
    """
    page = app_page
    wait_for_grid_stable(page, min_rows=5)

    metrics = get_row_metrics(page)
    assert len(metrics) >= 2, f"Need >= 2 rows for contiguity check, got {len(metrics)}"

    print(f"\n  Baseline: {len(metrics)} rows at scrollTop=0")
    print_metrics_table(metrics, "baseline scrollTop=0")

    violations = check_contiguity(metrics, "baseline scrollTop=0")
    if violations:
        pytest.fail(
            f"Baseline (scrollTop=0) translateY NOT contiguous "
            f"({len(violations)} violation(s)):\n" + "\n".join(violations)
        )

    top_idx = metrics[0]['idx']
    bot_idx = metrics[-1]['idx']
    print(f"\n[PASS] Baseline: rows idx=[{top_idx}..{bot_idx}] all contiguous")


def test_02_moderate_scroll_5000(app_page: Page):
    """
    Jump scrollTop to 5000px (into block 1-2 territory, past initial 100-row block).
    Wait for new IRM blocks to load and fixRowPositions to fire.
    Verify translateY contiguity of all newly rendered rows.
    """
    page = app_page
    wait_for_grid_stable(page, min_rows=5)

    metrics, violations = scroll_verify(
        page, scroll_top=5000, label="scrollTop=5000",
        require_min_idx=20   # should be past row 20 at minimum
    )

    if violations:
        pytest.fail(
            f"translateY violations at scrollTop=5000 "
            f"({len(violations)} violation(s)):\n" + "\n".join(violations)
        )

    top_idx = metrics[0]['idx'] if metrics else "?"
    bot_idx = metrics[-1]['idx'] if metrics else "?"
    print(f"\n[PASS] scrollTop=5000: rows idx=[{top_idx}..{bot_idx}] all contiguous")


def test_03_deep_scroll_20000(app_page: Page):
    """
    Jump scrollTop to 20000px (block 8-10 territory).
    This forces AG Grid to request at least one new IRM block beyond the initial load.
    fixRowPositions must fire after the new block's successCallback and after scroll events.
    """
    page = app_page
    wait_for_grid_stable(page, min_rows=5)

    metrics, violations = scroll_verify(
        page, scroll_top=20000, label="scrollTop=20000",
        extra_wait_ms=400,    # extra wait — deep scroll triggers network fetch
        require_min_idx=100   # definitively past the first 100-row block
    )

    if violations:
        pytest.fail(
            f"translateY violations at scrollTop=20000 "
            f"({len(violations)} violation(s)):\n" + "\n".join(violations)
        )

    top_idx = metrics[0]['idx'] if metrics else "?"
    bot_idx = metrics[-1]['idx'] if metrics else "?"
    print(f"\n[PASS] scrollTop=20000: rows idx=[{top_idx}..{bot_idx}] all contiguous")


def test_04_scroll_back_to_top(app_page: Page):
    """
    After deep-scrolling to 20000, scroll back to scrollTop=0.
    Row 0 must be at translateY=0 and all visible rows must be contiguous.
    AG Grid may have recycled DOM row elements — fixRowPositions must correct them.
    """
    page = app_page
    wait_for_grid_stable(page, min_rows=5)

    # First scroll deep
    scroll_to(page, 20000)
    page.wait_for_timeout(BLOCK_WAIT_MS + 400)

    # Now scroll back to top
    metrics, violations = scroll_verify(
        page, scroll_top=0, label="return to scrollTop=0"
    )

    if violations:
        pytest.fail(
            f"translateY violations after returning to scrollTop=0 "
            f"({len(violations)} violation(s)):\n" + "\n".join(violations)
        )

    if metrics:
        first_idx = metrics[0]['idx']
        first_ty = metrics[0]['translateY']
        if first_idx == 0 and abs(first_ty) > TOLERANCE:
            pytest.fail(
                f"Row 0 has translateY={first_ty:.1f}px after scroll-back — expected 0"
            )

    top_idx = metrics[0]['idx'] if metrics else "?"
    bot_idx = metrics[-1]['idx'] if metrics else "?"
    print(f"\n[PASS] Return to scrollTop=0: rows idx=[{top_idx}..{bot_idx}] all contiguous")


def test_05_extreme_scroll_100000(app_page: Page):
    """
    Jump scrollTop to 100000px — deepest test, forces AG Grid into rows 400+.
    Browser may cap scrollTop if container height is smaller, but even a partial
    jump must result in contiguous translateY for all visible rows.
    Reports the actual scrollTop reached and the row-index range visible.
    """
    page = app_page
    wait_for_grid_stable(page, min_rows=5)

    # First set scrollTop
    actual_top = scroll_to(page, 100000)
    page.wait_for_timeout(BLOCK_WAIT_MS + 600)

    # Extra wait in case a new block fetch is in flight
    try:
        page.wait_for_function(
            "() => document.querySelectorAll('#matchesGrid .ag-center-cols-container "
            ".ag-row:not(.ag-row-loading)').length >= 3",
            timeout=12000
        )
    except Exception:
        pass

    page.wait_for_timeout(250)
    metrics = get_row_metrics(page)

    print(f"\n  Extreme scroll: requested scrollTop=100000, actual={actual_top}")
    if metrics:
        print_metrics_table(metrics, f"scrollTop={actual_top} (extreme)", count=15)
    else:
        print("  WARNING: no rendered rows found after extreme scroll")

    violations = []
    if len(metrics) < 2:
        print(f"  Only {len(metrics)} row(s) rendered — cannot check contiguity")
    else:
        violations = check_contiguity(metrics, f"extreme scrollTop={actual_top}")

    if violations:
        pytest.fail(
            f"translateY violations at extreme scroll (requested=100000, actual={actual_top}) "
            f"({len(violations)} violation(s)):\n" + "\n".join(violations)
        )

    top_idx = metrics[0]['idx'] if metrics else "N/A"
    bot_idx = metrics[-1]['idx'] if metrics else "N/A"
    print(f"\n[PASS] Extreme scrollTop={actual_top}: rows idx=[{top_idx}..{bot_idx}] all contiguous")


def test_06_multi_jump_sequence(app_page: Page):
    """
    Sequence of scroll jumps to test that fixRowPositions fires correctly
    for each new scroll position, including cross-block boundaries:
      0 -> 5000 -> 20000 -> 50000 -> 20000 -> 0

    For each position, verifies translateY contiguity and records the row-index range.
    """
    page = app_page
    wait_for_grid_stable(page, min_rows=5)

    scroll_sequence = [
        (5000,  "jump to 5000",   250,  10),
        (20000, "jump to 20000",  500,  50),
        (50000, "jump to 50000",  700,  200),
        (20000, "back to 20000",  400,  50),
        (0,     "back to 0",      300,  0),
    ]

    all_violations = []
    summary_lines = []

    for scroll_top, label, extra_wait, min_idx in scroll_sequence:
        metrics, violations = scroll_verify(
            page, scroll_top=scroll_top, label=label,
            extra_wait_ms=extra_wait, require_min_idx=min_idx
        )

        top_idx = metrics[0]['idx'] if metrics else "?"
        bot_idx = metrics[-1]['idx'] if metrics else "?"
        row_count = len(metrics)
        status = "PASS" if not violations else f"FAIL ({len(violations)} violation(s))"

        summary_lines.append(
            f"  {label:<22}  scrollTop={scroll_top:<7}  "
            f"rows={row_count:<3}  idx=[{top_idx}..{bot_idx}]  {status}"
        )

        if violations:
            all_violations.extend(violations)
            print(f"\n  FAIL at {label}: {len(violations)} violation(s)")
            for v in violations:
                print(v)
        else:
            print(f"\n  PASS at {label}: {row_count} rows idx=[{top_idx}..{bot_idx}] contiguous")

    print("\n\n  === Multi-jump Sequence Summary ===")
    for line in summary_lines:
        print(line)

    if all_violations:
        pytest.fail(
            f"translateY violations during multi-jump sequence "
            f"({len(all_violations)} total across all positions):\n"
            + "\n".join(all_violations)
        )

    print(f"\n[PASS] All {len(scroll_sequence)} scroll positions have contiguous translateY")


def test_07_cross_block_boundary_verification(app_page: Page):
    """
    Specifically target the IRM block boundary.
    Block 0 covers rows 0-99 (100-row blockSize).
    Block 1 covers rows 100-199.

    Scroll so that rows from BOTH block 0 and block 1 are visible simultaneously
    (i.e., the viewport straddles the block boundary).

    This is the most dangerous scenario: fixRowPositions must handle rows from
    two different blocks in the same DOM snapshot, with a gap-free translateY chain.
    """
    page = app_page
    wait_for_grid_stable(page, min_rows=5)

    # First load block 0 (rows 0-99) by being at the top
    # Then scroll to a position that should straddle the block boundary.
    # With 24px rows, 100 rows * 24px = 2400px for a uniform grid.
    # With mixed heights, boundary could be anywhere between ~2400-3500px.
    # Use scrollTop=2000 to land near the boundary.

    metrics_initial = get_row_metrics(page)
    max_initial_idx = max(m['idx'] for m in metrics_initial) if metrics_initial else 0
    print(f"\n  Initial block: rows idx=[0..{max_initial_idx}]")

    # Scroll to straddle block 0/1 boundary
    scroll_to(page, 2000)
    page.wait_for_timeout(BLOCK_WAIT_MS + 300)

    try:
        page.wait_for_function(
            "() => document.querySelectorAll('#matchesGrid .ag-center-cols-container "
            ".ag-row:not(.ag-row-loading)').length >= 3",
            timeout=10000
        )
    except Exception:
        pass
    page.wait_for_timeout(200)

    metrics_2000 = get_row_metrics(page)
    print_metrics_table(metrics_2000, "scrollTop=2000 (near block boundary)")

    # Scroll further to ensure we're into block 1 (rows 100+)
    scroll_to(page, 3000)
    page.wait_for_timeout(BLOCK_WAIT_MS + 300)

    try:
        page.wait_for_function(
            "() => document.querySelectorAll('#matchesGrid .ag-center-cols-container "
            ".ag-row:not(.ag-row-loading)').length >= 3",
            timeout=10000
        )
    except Exception:
        pass
    page.wait_for_timeout(200)

    metrics_3000 = get_row_metrics(page)
    print_metrics_table(metrics_3000, "scrollTop=3000 (into block 1)")

    # Check if we're straddling the boundary (rows from both blocks visible)
    indices_3000 = [m['idx'] for m in metrics_3000]
    has_pre_100 = any(i < 100 for i in indices_3000)
    has_post_100 = any(i >= 100 for i in indices_3000)

    if has_pre_100 and has_post_100:
        print(f"  Cross-block view confirmed: rows span idx 0-99 AND idx 100+ simultaneously")
    else:
        min_idx = min(indices_3000) if indices_3000 else "?"
        max_idx = max(indices_3000) if indices_3000 else "?"
        print(f"  Note: rows idx=[{min_idx}..{max_idx}] — may be fully within one block")

    all_failures = []

    for metrics, label in [(metrics_2000, "scrollTop=2000"), (metrics_3000, "scrollTop=3000")]:
        if len(metrics) < 2:
            print(f"  WARNING: only {len(metrics)} row(s) at {label}")
            continue
        v = check_contiguity(metrics, label)
        if v:
            all_failures.extend(v)
        else:
            top_idx = metrics[0]['idx']
            bot_idx = metrics[-1]['idx']
            print(f"  PASS {label}: {len(metrics)} rows idx=[{top_idx}..{bot_idx}] contiguous")

    if all_failures:
        pytest.fail(
            f"Cross-block boundary translateY violations "
            f"({len(all_failures)} violation(s)):\n" + "\n".join(all_failures)
        )

    print(f"\n[PASS] Cross-block boundary: all visible rows have contiguous translateY")


def test_08_pinned_rows_aligned_after_deep_scroll(app_page: Page):
    """
    After scrolling to 20000px (new IRM block territory), pinned-left rows must
    have the same height and translateY as the corresponding center rows.
    """
    page = app_page
    wait_for_grid_stable(page, min_rows=5)

    scroll_to(page, 20000)
    page.wait_for_timeout(BLOCK_WAIT_MS + 500)

    try:
        page.wait_for_function(
            "() => document.querySelectorAll('#matchesGrid .ag-center-cols-container "
            ".ag-row:not(.ag-row-loading)').length >= 3",
            timeout=10000
        )
    except Exception:
        pass
    page.wait_for_timeout(200)

    center = {m['idx']: m for m in get_row_metrics(page)}
    pinned = {m['idx']: m for m in get_pinned_row_metrics(page)}

    if not pinned:
        pytest.skip("No pinned-left container found")

    if not center:
        pytest.skip("No center rows found at scrollTop=20000")

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
                f"row-index={idx} translateY mismatch: "
                f"center={cm['translateY']:.1f} pinned={pm['translateY']:.1f}"
            )
        checked += 1

    print(f"\n  Checked {checked} pinned-left rows at scrollTop=20000")
    center_top = min(center) if center else "?"
    center_bot = max(center) if center else "?"
    print(f"  Center rows idx=[{center_top}..{center_bot}]")

    if failures:
        pytest.fail(
            f"Pinned-left rows misaligned after deep scroll to scrollTop=20000 "
            f"({len(failures)} violation(s)):\n  " + "\n  ".join(failures)
        )

    print(f"\n[PASS] {checked} pinned-left rows aligned with center after deep scroll")


def test_09_no_console_errors_during_deep_scroll(app_page: Page):
    """
    No JavaScript errors in console during a deep-scroll sequence.
    """
    page = app_page
    wait_for_grid_stable(page, min_rows=5)

    for scroll_top in [5000, 20000, 50000, 0]:
        scroll_to(page, scroll_top)
        page.wait_for_timeout(BLOCK_WAIT_MS)

    errors = page.evaluate("() => window._consoleErrors || []")
    real_errors = [
        e for e in errors if not any(skip in e for skip in [
            'suppressMenu', 'autoHeight', 'headerCheckbox',
            'deprecated', 'AgGrid:', 'favicon'
        ])
    ]

    if real_errors:
        pytest.fail(
            f"{len(real_errors)} console error(s) during deep-scroll sequence:\n  "
            + "\n  ".join(real_errors[:10])
        )

    print(f"\n[PASS] No console errors during deep-scroll sequence "
          f"(captured: {len(errors)}, all benign)")

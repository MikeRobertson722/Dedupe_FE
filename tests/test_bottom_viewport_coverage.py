"""
Regression test: after a scroll burst, the rendered rows in
.ag-center-cols-container must cover the bottom of the viewport.

Bug being captured:
  User reports a permanent blank area at the BOTTOM of the grid viewport
  after scrolling (especially large amounts, or small amounts fast). The
  top of the viewport renders fine; the bottom shows white space below the
  last visible row until page refresh.

Mechanism:
  fixRowPositions() reads each rendered row's offsetHeight and stacks them
  cumulatively starting at top_idx * 24. If any row's offsetHeight is 0
  (autoHeight not yet measured, or loading placeholder), it contributes 0
  to cumY. The cumulative sum then falls short of N * 24, so the last
  rendered row's bottom ends BEFORE the viewport bottom. AG Grid's own
  scroll math (based on rowHeight=24) thinks the viewport is covered, so
  it never renders more rows. Result: permanent gap.

This test:
  - Scrolls to several positions using rapid PageDown bursts.
  - At each position, after the grid settles, computes
      content_bottom = max(row.translateY + row.offsetHeight) over all rendered rows
      viewport_bottom = viewport.scrollTop + viewport.clientHeight
  - Fails if content_bottom < viewport_bottom (rendered area falls short).
"""

import pytest
from playwright.sync_api import Page


SETTLE_WAIT_MS = 400        # Wait for scroll-end + RAF + autoHeight measurement
COVERAGE_TOLERANCE_PX = 2   # Sub-pixel rounding tolerance


def wait_for_grid_stable(page: Page, min_rows: int = 5, timeout: int = 20000):
    page.wait_for_function(
        f"() => document.querySelectorAll('#matchesGrid .ag-center-cols-container .ag-row').length >= {min_rows}",
        timeout=timeout,
    )
    page.wait_for_function(
        "() => { var t = document.querySelector('#gridInfo'); "
        "return t && /\\d/.test(t.innerText) && t.innerText !== '0 records'; }",
        timeout=10000,
    )
    page.wait_for_timeout(300)


def focus_grid(page: Page):
    page.locator('.ag-center-cols-viewport').first.click()
    page.wait_for_timeout(80)


def viewport_coverage(page: Page) -> dict:
    """
    Returns the coverage measurement at the current scroll position.
    {
        scrollTop, clientHeight, viewportBottom,
        topY, bottomY, contentBottom,   # contentBottom = max(translateY + offsetHeight)
        gap,                            # viewportBottom - contentBottom (positive = blank gap)
        rowCount,
        rows: [{idx, translateY, height}, ...]  # for debug
    }
    """
    return page.evaluate(
        """
        () => {
            var viewport = document.querySelector('#matchesGrid .ag-body-viewport')
                || document.querySelector('.ag-body-viewport');
            var container = document.querySelector('#matchesGrid .ag-center-cols-container')
                || document.querySelector('.ag-center-cols-container');
            if (!viewport || !container) return { error: 'viewport or container not found' };

            var nodes = container.querySelectorAll('.ag-row:not(.ag-row-loading)');
            var rows = [];
            var contentBottom = -Infinity;
            var topY = Infinity;
            nodes.forEach(function(el) {
                var idx = parseInt(el.getAttribute('row-index'), 10);
                if (isNaN(idx)) return;
                var t = el.style.transform || '';
                var m = t.match(/translateY\\(([-\\d.]+)px\\)/);
                var y = m ? parseFloat(m[1]) : 0;
                var h = el.offsetHeight;
                rows.push({ idx: idx, translateY: y, height: h });
                if (y < topY) topY = y;
                if (y + h > contentBottom) contentBottom = y + h;
            });
            rows.sort(function(a, b) { return a.idx - b.idx; });

            var scrollTop = viewport.scrollTop;
            var clientHeight = viewport.clientHeight;
            var viewportBottom = scrollTop + clientHeight;
            return {
                scrollTop: scrollTop,
                clientHeight: clientHeight,
                viewportBottom: viewportBottom,
                topY: topY === Infinity ? null : topY,
                bottomY: contentBottom === -Infinity ? null : contentBottom,
                contentBottom: contentBottom === -Infinity ? null : contentBottom,
                gap: contentBottom === -Infinity ? null : (viewportBottom - contentBottom),
                rowCount: rows.length,
                rows: rows
            };
        }
        """
    )


def _assert_covers(page: Page, where: str):
    cov = viewport_coverage(page)
    assert 'error' not in cov, f"{where}: coverage probe error: {cov.get('error')}"
    assert cov['rowCount'] > 0, f"{where}: no rendered rows in center container"
    print(
        f"  {where}: scrollTop={cov['scrollTop']:.0f}, "
        f"viewportBottom={cov['viewportBottom']:.0f}, "
        f"contentBottom={cov['contentBottom']:.1f}, "
        f"gap={cov['gap']:+.1f}px, rows={cov['rowCount']}"
    )
    # gap = viewportBottom - contentBottom; positive gap = blank area at bottom
    if cov['gap'] > COVERAGE_TOLERANCE_PX:
        # Show a small slice of rows for debugging
        sample = cov['rows'][:5] + (['...'] if len(cov['rows']) > 10 else []) + cov['rows'][-5:]
        print(f"    row sample: {sample}")
        pytest.fail(
            f"BOTTOM-OF-VIEWPORT BLANK at {where}: "
            f"rendered content ends at y={cov['contentBottom']:.1f}, "
            f"but viewport extends to y={cov['viewportBottom']:.0f} "
            f"({cov['gap']:.1f}px of blank space at viewport bottom)."
        )


def test_viewport_covered_after_short_scroll(app_page: Page):
    """One PageDown — minimal scroll, rendered content must cover viewport."""
    page = app_page
    wait_for_grid_stable(page, min_rows=5)
    focus_grid(page)

    page.keyboard.press("PageDown")
    page.wait_for_timeout(SETTLE_WAIT_MS)

    _assert_covers(page, "after 1x PageDown")


def test_viewport_covered_after_rapid_burst(app_page: Page):
    """10 rapid PageDowns with no inter-press delay — the user's symptom."""
    page = app_page
    wait_for_grid_stable(page, min_rows=5)
    focus_grid(page)

    for _ in range(10):
        page.keyboard.press("PageDown")
    page.wait_for_timeout(SETTLE_WAIT_MS)

    _assert_covers(page, "after 10x rapid PageDown")


def test_viewport_covered_at_multiple_scroll_positions(app_page: Page):
    """
    Probe coverage at ~10%, ~50%, ~90% of total scrollHeight via direct
    scrollTop sets. This exercises the same code path the user hits when
    they jump around the grid quickly.
    """
    page = app_page
    wait_for_grid_stable(page, min_rows=5)
    focus_grid(page)

    geom = page.evaluate(
        """
        () => {
            var v = document.querySelector('#matchesGrid .ag-body-viewport')
                 || document.querySelector('.ag-body-viewport');
            return { scrollHeight: v.scrollHeight, clientHeight: v.clientHeight };
        }
        """
    )
    max_scroll = max(0, geom['scrollHeight'] - geom['clientHeight'])
    print(f"\n  scrollHeight={geom['scrollHeight']}, clientHeight={geom['clientHeight']}, "
          f"max_scroll={max_scroll}")
    if max_scroll < geom['clientHeight'] * 2:
        pytest.skip(f"Not enough data to scroll meaningfully (max_scroll={max_scroll})")

    for pct in (0.10, 0.50, 0.90):
        target = int(max_scroll * pct)
        page.evaluate(
            """
            (target) => {
                var v = document.querySelector('#matchesGrid .ag-body-viewport')
                     || document.querySelector('.ag-body-viewport');
                v.scrollTop = target;
            }
            """,
            target,
        )
        page.wait_for_timeout(SETTLE_WAIT_MS)
        _assert_covers(page, f"at {int(pct * 100)}% scroll (scrollTop={target})")


def test_viewport_covered_after_scroll_down_then_back_up(app_page: Page):
    """Scroll down hard, then back up — the gap must not appear on the way up."""
    page = app_page
    wait_for_grid_stable(page, min_rows=5)
    focus_grid(page)

    for _ in range(8):
        page.keyboard.press("PageDown")
    page.wait_for_timeout(SETTLE_WAIT_MS)
    _assert_covers(page, "after 8x PageDown")

    for _ in range(4):
        page.keyboard.press("PageUp")
    page.wait_for_timeout(SETTLE_WAIT_MS)
    _assert_covers(page, "after 4x PageUp")

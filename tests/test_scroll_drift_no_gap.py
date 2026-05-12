"""
Regression test: fixRowPositions drift compounding causes a white gap
between the headers and the topmost rendered row.

Symptom (captured from a live session at scrollTop=15814):
  scrollTop:        15814
  Topmost row Y:    16056   ← 242px below scrollTop
  Result:           Viewport's top 242px is empty (white area below headers).

Root cause:
  fixRowPositions reads rowList[0].el.style.transform as the starting cumY.
  On scroll, AG Grid recycles DOM rows for new indices but does not always
  reset the transform. The next fixRowPositions call inherits the prior
  output's Y as its input, and the drift compounds across many small scroll
  events. Single big scrollTop jumps (as in test_deep_scroll_contiguity.py)
  fire fixRowPositions only once and so don't compound — that's why this
  bug slips past those tests.

Reproduction: many small mouse-wheel scroll events. The drift accumulates
proportionally to the number of fires.

Invariant under test:
  After any scroll, the topmost rendered row's translateY must be at or
  just above scrollTop (within a small tolerance for rendering overscan).
  It must NOT be substantially BELOW scrollTop — that produces visible
  white space below the headers.
"""

import pytest
from playwright.sync_api import Page


# How far below scrollTop the first row may be before we call it a gap.
# Anything > one default row height is visible white space the user notices.
GAP_TOLERANCE_PX = 30

# How many small wheel ticks to perform. Mouse wheels emit dozens of
# 100-300px deltas per second; we need enough to force many fixRowPositions
# fires and compound any drift.
WHEEL_TICKS = 50
WHEEL_DELTA_PX = 300


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


def capture_state(page: Page) -> dict:
    """Snapshot scrollTop and the topmost rendered row's position."""
    return page.evaluate(
        """
        () => {
            const c = document.querySelector('#matchesGrid .ag-center-cols-container');
            const vp = document.querySelector('.ag-body-viewport');
            if (!c || !vp) return null;
            const rows = Array.from(c.querySelectorAll('.ag-row:not(.ag-row-loading)'))
                .map(r => {
                    const m = (r.style.transform || '').match(/translateY\\(([-\\d.]+)px\\)/);
                    return {
                        idx: parseInt(r.getAttribute('row-index'), 10),
                        y: m ? parseFloat(m[1]) : null,
                        h: r.offsetHeight,
                    };
                })
                .filter(r => r.y !== null && !isNaN(r.idx))
                .sort((a, b) => a.y - b.y);
            return {
                scrollTop: vp.scrollTop,
                viewportH: vp.clientHeight,
                containerStyleH: c.style.height,
                rowCount: rows.length,
                firstRow: rows[0] || null,
                lastRow: rows[rows.length - 1] || null,
            };
        }
        """
    )


def test_no_gap_after_continuous_wheel_scroll(app_page: Page):
    """
    Mouse-wheel scroll in many small segments, each followed by a pause
    long enough for onBodyScrollEnd to fire and fixRowPositions to settle.
    This is the real-user pattern: many discrete scroll segments, each
    triggering its own fixRowPositions call. Drift compounds across calls
    because each call reads the prior call's translateY output as its
    starting point.
    """
    page = app_page
    wait_for_grid_stable(page, min_rows=5)

    # Hover over the grid body so wheel events go to the viewport.
    grid_body = page.locator(".ag-center-cols-viewport").first
    grid_body.hover()

    # 50 discrete scroll segments, each separated by a pause that lets
    # onBodyScrollEnd fire + 100ms debounce + DOM settle.
    for _ in range(WHEEL_TICKS):
        page.mouse.wheel(0, WHEEL_DELTA_PX)
        page.wait_for_timeout(180)

    # Let the final fixRowPositions settle.
    page.wait_for_timeout(400)

    state = capture_state(page)
    assert state is not None, "Grid containers not found"

    print(
        f"\n  After {WHEEL_TICKS} wheel ticks: "
        f"scrollTop={state['scrollTop']}, "
        f"containerStyleH={state['containerStyleH']}, "
        f"rowCount={state['rowCount']}, "
        f"firstRow={state['firstRow']}, "
        f"lastRow={state['lastRow']}"
    )

    if state["rowCount"] == 0:
        pytest.fail("Grid blanked: 0 rendered rows after wheel scroll")

    first = state["firstRow"]
    scroll_top = state["scrollTop"]
    gap = first["y"] - scroll_top  # positive = row is BELOW scrollTop (the bug)

    if gap > GAP_TOLERANCE_PX:
        pytest.fail(
            f"Gap below headers: topmost row (idx={first['idx']}) is at "
            f"Y={first['y']}, which is {gap}px BELOW scrollTop={scroll_top}. "
            f"Tolerance is {GAP_TOLERANCE_PX}px. This is the "
            f"white-area-below-headers symptom of fixRowPositions drift compounding."
        )

    print(
        f"[PASS] No gap: topmost row Y={first['y']} is "
        f"{abs(gap)}px {'above' if gap < 0 else 'at-or-below'} scrollTop={scroll_top}"
    )


def test_no_gap_after_repeated_pagedown(app_page: Page):
    """
    PageDown 30 times in succession. Each PageDown fires onBodyScrollEnd
    which fires fixRowPositions. With drift compounding, the topmost row
    Y will drift away from scrollTop. This complements the wheel-scroll
    test by using a different scroll input.
    """
    page = app_page
    wait_for_grid_stable(page, min_rows=5)

    grid_body = page.locator(".ag-center-cols-viewport").first
    grid_body.click()
    page.wait_for_timeout(80)

    # 30 discrete PageDown presses, each followed by a pause that lets
    # onBodyScrollEnd fire + 100ms debounce settle. Compounds fixRowPositions
    # drift across many calls.
    for _ in range(30):
        page.keyboard.press("PageDown")
        page.wait_for_timeout(180)

    page.wait_for_timeout(400)

    state = capture_state(page)
    assert state is not None, "Grid containers not found"

    print(
        f"\n  After 30x PageDown: "
        f"scrollTop={state['scrollTop']}, "
        f"rowCount={state['rowCount']}, "
        f"firstRow={state['firstRow']}"
    )

    if state["rowCount"] == 0:
        pytest.fail("Grid blanked: 0 rendered rows after PageDown burst")

    first = state["firstRow"]
    scroll_top = state["scrollTop"]
    gap = first["y"] - scroll_top

    if gap > GAP_TOLERANCE_PX:
        pytest.fail(
            f"Gap below headers after 30x PageDown: topmost row "
            f"(idx={first['idx']}) at Y={first['y']} is {gap}px BELOW "
            f"scrollTop={scroll_top}. Tolerance is {GAP_TOLERANCE_PX}px."
        )

    print(
        f"[PASS] No gap: topmost row Y={first['y']} is "
        f"{abs(gap)}px {'above' if gap < 0 else 'at-or-below'} scrollTop={scroll_top}"
    )

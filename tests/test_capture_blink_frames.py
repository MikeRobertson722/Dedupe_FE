"""
Visual capture of the pre-fix ("blink") frame.

The previous test confirmed timing (220 ms gap between scroll-end and the
row-position rewrite) but page.screenshot() blocks until paint, so by the
time the bitmap returns the fix has already run — we only got the settled
state on both shots.

Approach here: temporarily intercept window.setTimeout in the page and turn
any 100 ms delay into 3000 ms. That stretches the post-scroll-end window
where rows are still at AG Grid's default idx*24 positions, giving
Playwright a comfortable 3-second window to capture the wrong-position
frame. After the screenshot we restore setTimeout and let the fix run
so the third screenshot shows the corrected state.

No app code is modified. This is a test-only manipulation, in-page.
"""

import pytest
from playwright.sync_api import Page


SMALL_WHEEL_PX = 120
DELAY_BEFORE_FIX_SCREENSHOT_MS = 400  # wait long enough for AG Grid to paint
                                       # rows at idx*24, but well before our
                                       # stretched 3000ms fix timer fires.


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


def patch_set_timeout(page: Page, target_delay_ms: int = 100, replacement_ms: int = 3000):
    """Wrap window.setTimeout so calls with delay === target_delay_ms use
    replacement_ms instead. Records how many calls were intercepted."""
    page.evaluate(
        """
        ([target, repl]) => {
            if (window.__origSetTimeout) return; // already patched
            window.__origSetTimeout = window.setTimeout;
            window.__stPatches = 0;
            window.setTimeout = function(fn, delay) {
                var d = delay;
                if (delay === target) {
                    d = repl;
                    window.__stPatches += 1;
                }
                var args = Array.prototype.slice.call(arguments, 2);
                return window.__origSetTimeout.apply(window,
                    [fn, d].concat(args));
            };
        }
        """,
        [target_delay_ms, replacement_ms],
    )


def unpatch_set_timeout(page: Page):
    page.evaluate(
        """() => {
            if (window.__origSetTimeout) {
                window.setTimeout = window.__origSetTimeout;
                window.__origSetTimeout = null;
            }
        }"""
    )


def row_positions(page: Page):
    return page.evaluate(
        """
        () => {
            var c = document.querySelector('#matchesGrid .ag-center-cols-container');
            if (!c) return [];
            return Array.from(c.querySelectorAll('.ag-row:not(.ag-row-loading)'))
                .map(r => {
                    var m = /translateY\\(([-\\d.]+)px\\)/.exec(r.style.transform || '');
                    return {
                        idx: parseInt(r.getAttribute('row-index'), 10),
                        h: r.offsetHeight,
                        y: m ? parseFloat(m[1]) : null,
                    };
                })
                .filter(r => !isNaN(r.idx) && r.y !== null)
                .sort((a, b) => a.idx - b.idx);
        }
        """
    )


def test_capture_blink_frames(app_page: Page, tmp_path):
    page = app_page
    wait_for_grid_stable(page, min_rows=5)

    # --- Phase 0: scroll well into the dataset so multi-line rows exist
    #     above the visible viewport and the recycled rows on the *next*
    #     wheel land inside the viewport. We do this without stretching
    #     the timer so the grid settles normally first. ---
    grid_body = page.locator(".ag-center-cols-viewport").first
    grid_body.hover()
    for _ in range(8):
        page.mouse.wheel(0, 600)
        page.wait_for_timeout(180)
    page.wait_for_timeout(500)  # let the last fixRowPositions settle

    # --- Frame 1: settled state at the new scroll position ---
    pre_path = tmp_path / "01_pre_scroll.png"
    page.screenshot(path=str(pre_path))
    pre_rows = row_positions(page)

    # --- Now stretch the 100ms fixRowPositions debounce to 3000ms ---
    patch_set_timeout(page, target_delay_ms=100, replacement_ms=3000)

    # --- Trigger the scroll we want to study ---
    grid_body.hover()
    page.mouse.wheel(0, SMALL_WHEEL_PX)

    # --- Wait long enough for AG Grid to paint at idx*24 but well before
    #     our stretched 3000ms fix timer fires ---
    page.wait_for_timeout(DELAY_BEFORE_FIX_SCREENSHOT_MS)

    # --- Frame 2: AG Grid has scrolled but fixRowPositions has NOT run ---
    wrong_path = tmp_path / "02_post_scroll_pre_fix.png"
    page.screenshot(path=str(wrong_path))
    wrong_rows = row_positions(page)

    # --- Restore setTimeout and wait for the fix to fire ---
    unpatch_set_timeout(page)
    page.wait_for_timeout(3200)

    # --- Frame 3: fix has run, rows are at corrected positions ---
    settled_path = tmp_path / "03_post_scroll_settled.png"
    page.screenshot(path=str(settled_path))
    settled_rows = row_positions(page)

    # --- Diagnostic print ---
    def fmt_rows(rs, label, n=12):
        print(f"\n  {label} (first {n} rendered rows by idx):")
        for r in rs[:n]:
            marker = "  <-- multi-line" if r['h'] > 25 else ""
            print(f"    idx={r['idx']:>4}  h={r['h']:>3}px  translateY={r['y']:.1f}{marker}")
        print(f"    ... ({len(rs)} rows total)")

    patches = page.evaluate("() => window.__stPatches || 0")
    print(f"\n  setTimeout(100ms) intercepts during scroll: {patches}")
    print(f"  screenshots saved to {tmp_path}")
    fmt_rows(pre_rows,     "BEFORE scroll          ")
    fmt_rows(wrong_rows,   "AFTER scroll, pre-fix  (AG Grid's idx*24 placement)")
    fmt_rows(settled_rows, "AFTER scroll, post-fix (fixRowPositions applied)")

    # Sanity: at least one row in 'wrong' must differ in translateY from 'settled'
    # at the same idx, otherwise the fix isn't actually moving anything.
    settled_by_idx = {r["idx"]: r for r in settled_rows}
    diffs = []
    for r in wrong_rows:
        s = settled_by_idx.get(r["idx"])
        if s is None:
            continue
        dy = s["y"] - r["y"]
        if abs(dy) > 1:
            diffs.append((r["idx"], r["y"], s["y"], dy))

    print(f"\n  Rows whose translateY differs between pre-fix and post-fix: {len(diffs)}")
    for idx, wy, sy, dy in diffs[:10]:
        print(f"    idx={idx:>4}  pre-fix y={wy:.1f}  post-fix y={sy:.1f}  shift={dy:+.1f}px")

    assert patches >= 1, "setTimeout patch never intercepted a 100ms delay"
    if not diffs:
        pytest.fail(
            "Pre-fix and post-fix translateY values are identical — either the "
            "fix didn't fire, or the patch was bypassed. Check window.__stPatches."
        )

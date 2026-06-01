"""
One-off manual-verification harness — runs after the bottom-viewport-blank fix
to confirm the fix holds end-to-end against the live Flask app.

Drives the grid through realistic user scroll patterns, captures screenshots
at each step, and reports the coverage measurement so the change can be
manually eyeballed against the saved screenshots if anyone wants to.

Run: pytest tests/test_manual_verification.py -v -s
Screenshots land in: C:/ClaudeMain/BA_Review_App/tests/_screens/
"""

import os
import pytest
from playwright.sync_api import Page

OUT_DIR = r"C:\ClaudeMain\BA_Review_App\tests\_screens"
os.makedirs(OUT_DIR, exist_ok=True)


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


def coverage(page: Page) -> dict:
    return page.evaluate(
        """
        () => {
            var viewport = document.querySelector('#matchesGrid .ag-body-viewport')
                || document.querySelector('.ag-body-viewport');
            var container = document.querySelector('#matchesGrid .ag-center-cols-container')
                || document.querySelector('.ag-center-cols-container');
            if (!viewport || !container) return {};
            var nodes = container.querySelectorAll('.ag-row:not(.ag-row-loading)');
            var contentBottom = -Infinity;
            var rowCount = 0;
            nodes.forEach(function(el) {
                var t = el.style.transform || '';
                var m = t.match(/translateY\\(([-\\d.]+)px\\)/);
                var y = m ? parseFloat(m[1]) : 0;
                var h = el.offsetHeight;
                if (y + h > contentBottom) contentBottom = y + h;
                rowCount++;
            });
            return {
                scrollTop: viewport.scrollTop,
                clientHeight: viewport.clientHeight,
                viewportBottom: viewport.scrollTop + viewport.clientHeight,
                contentBottom: contentBottom === -Infinity ? null : contentBottom,
                gap: contentBottom === -Infinity ? null : (viewport.scrollTop + viewport.clientHeight - contentBottom),
                rowCount: rowCount,
                gridInfo: (document.querySelector('#gridInfo') || {}).innerText || ''
            };
        }
        """
    )


def snap(page: Page, name: str, cov: dict):
    path = os.path.join(OUT_DIR, name + ".png")
    page.screenshot(path=path)
    status = "OK" if (cov.get('gap') is None or cov['gap'] <= 2) else "BLANK"
    print(
        f"  [{status}] {name}: scrollTop={cov.get('scrollTop')}, "
        f"viewportBottom={cov.get('viewportBottom')}, "
        f"contentBottom={cov.get('contentBottom')}, "
        f"gap={cov.get('gap')}px, rows={cov.get('rowCount')}  -> {path}"
    )
    return cov


def test_manual_verification(app_page: Page):
    page = app_page
    wait_for_grid_stable(page, min_rows=5)

    # 1. Baseline (no scroll)
    snap(page, "01_baseline", coverage(page))

    # 2. Click into the grid
    page.locator('.ag-center-cols-viewport').first.click()
    page.wait_for_timeout(80)

    # 3. Single PageDown
    page.keyboard.press("PageDown")
    page.wait_for_timeout(400)
    snap(page, "02_after_1x_PageDown", coverage(page))

    # 4. Rapid burst of 10 PageDowns (the user's "scrolling small amounts quickly")
    for _ in range(10):
        page.keyboard.press("PageDown")
    page.wait_for_timeout(500)
    snap(page, "03_after_10x_rapid_PageDown", coverage(page))

    # 5. Jump to 50% via direct scrollTop (user's "large amounts")
    geom = page.evaluate(
        """() => {
            var v = document.querySelector('#matchesGrid .ag-body-viewport')
                 || document.querySelector('.ag-body-viewport');
            return { scrollHeight: v.scrollHeight, clientHeight: v.clientHeight };
        }"""
    )
    max_scroll = max(0, geom['scrollHeight'] - geom['clientHeight'])
    print(f"\n  max_scroll = {max_scroll}px ({geom})")

    for pct in (0.10, 0.50, 0.90, 1.00):
        target = int(max_scroll * pct)
        page.evaluate(
            """(t) => {
                var v = document.querySelector('#matchesGrid .ag-body-viewport')
                     || document.querySelector('.ag-body-viewport');
                v.scrollTop = t;
            }""",
            target,
        )
        page.wait_for_timeout(450)
        snap(page, f"04_scroll_{int(pct * 100):03d}pct", coverage(page))

    # 6. Mouse-wheel small bursts (closest to the user's reported small-fast pattern)
    page.locator('.ag-center-cols-viewport').first.hover()
    for _ in range(8):
        page.mouse.wheel(0, 80)
    page.wait_for_timeout(450)
    snap(page, "05_after_wheel_burst", coverage(page))

    # 7. Final scroll all the way back to top
    page.evaluate(
        """() => {
            var v = document.querySelector('#matchesGrid .ag-body-viewport')
                 || document.querySelector('.ag-body-viewport');
            v.scrollTop = 0;
        }"""
    )
    page.wait_for_timeout(450)
    snap(page, "06_back_to_top", coverage(page))

    print(f"\nScreenshots saved to: {OUT_DIR}")

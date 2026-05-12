"""
Non-interactive sibling of record_scroll_video.py.

Runs Playwright (headless) with video recording, executes a battery of
scroll patterns against the running app, captures a MutationObserver
trace of row-position changes + block-load fetches, and writes both
recordings/auto_<timestamp>.webm and recordings/auto_<timestamp>.trace.json.

Use when you want a video produced for you to review, without having to
scroll the browser yourself.
"""
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


APP_URL = "http://127.0.0.1:5000"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
VIDEO_DIR = PROJECT_ROOT / "recordings"
VIDEO_DIR.mkdir(exist_ok=True)


TRACE_JS = """
() => {
    window.__scrollTrace = {
        installedAt: performance.now(),
        scrollEvents: [],
        mutations: [],
        getRowsCalls: [],
        markers: [],
    };
    window.__mark = function(label) {
        window.__scrollTrace.markers.push({ t: performance.now(), label: label });
    };

    var vp = document.querySelector('#matchesGrid .ag-body-viewport')
          || document.querySelector('.ag-body-viewport');
    if (vp) {
        vp.addEventListener('scroll', function() {
            window.__scrollTrace.scrollEvents.push({
                t: performance.now(),
                top: vp.scrollTop,
            });
        }, { passive: true });
    }

    function parseY(s) {
        if (!s) return null;
        var m = /translateY\\(([-\\d.]+)px\\)/.exec(s);
        return m ? parseFloat(m[1]) : null;
    }
    var container = document.querySelector('#matchesGrid .ag-center-cols-container');
    if (container) {
        var obs = new MutationObserver(function(records) {
            var now = performance.now();
            for (var i = 0; i < records.length; i++) {
                var r = records[i];
                if (r.attributeName !== 'style') continue;
                var el = r.target;
                if (!(el instanceof HTMLElement)) continue;
                if (!el.classList.contains('ag-row')) continue;
                var idx = parseInt(el.getAttribute('row-index'), 10);
                if (isNaN(idx)) continue;
                var oldY = parseY(r.oldValue || '');
                var newY = parseY(el.style.transform || '');
                if (oldY === newY) continue;
                window.__scrollTrace.mutations.push({
                    t: now, idx: idx, oldY: oldY, newY: newY,
                    deltaY: (oldY !== null && newY !== null) ? (newY - oldY) : null,
                    height: el.offsetHeight,
                });
            }
        });
        obs.observe(container, {
            attributes: true,
            attributeOldValue: true,
            attributeFilter: ['style'],
            subtree: true,
        });
    }

    var origFetch = window.fetch;
    window.fetch = function(input, init) {
        var url = (typeof input === 'string') ? input : (input && input.url);
        var start = performance.now();
        if (url && url.indexOf('/api/matches') !== -1) {
            return origFetch.apply(this, arguments).then(function(r) {
                window.__scrollTrace.getRowsCalls.push({
                    t_start: start, t_end: performance.now(),
                    url: url, duration_ms: performance.now() - start,
                });
                return r;
            });
        }
        return origFetch.apply(this, arguments);
    };
    return true;
}
"""


def mark(page, label):
    page.evaluate(f"() => window.__mark && window.__mark({json.dumps(label)})")


def main():
    stamp = int(time.time())
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            record_video_dir=str(VIDEO_DIR),
            record_video_size={"width": 1280, "height": 720},
        )
        page = context.new_page()
        print(f"Loading {APP_URL} ...")
        page.goto(APP_URL)
        page.wait_for_selector("#matchesGrid .ag-row", timeout=30000)
        page.wait_for_function(
            "() => { var t = document.querySelector('#gridInfo'); "
            "return t && /\\d/.test(t.innerText) && t.innerText !== '0 records'; }",
            timeout=15000,
        )
        page.wait_for_timeout(800)
        page.evaluate(TRACE_JS)

        viewport = page.locator(".ag-center-cols-viewport").first
        viewport.hover()
        page.wait_for_timeout(500)

        # Pattern A: a single small wheel (the "even a little scroll" case)
        mark(page, "A_small_wheel_start")
        page.mouse.wheel(0, 120)
        page.wait_for_timeout(600)
        mark(page, "A_small_wheel_end")
        page.wait_for_timeout(400)

        # Pattern B: many small wheel ticks in succession (real-user wheel)
        mark(page, "B_many_small_wheels_start")
        for _ in range(20):
            page.mouse.wheel(0, 200)
            page.wait_for_timeout(120)
        mark(page, "B_many_small_wheels_end")
        page.wait_for_timeout(500)

        # Pattern C: one big wheel jump (page-down-like)
        mark(page, "C_big_wheel_start")
        page.mouse.wheel(0, 2000)
        page.wait_for_timeout(800)
        mark(page, "C_big_wheel_end")
        page.wait_for_timeout(500)

        # Pattern D: 10 PageDown in succession
        viewport.click()
        page.wait_for_timeout(150)
        mark(page, "D_pagedown_burst_start")
        for _ in range(10):
            page.keyboard.press("PageDown")
            page.wait_for_timeout(160)
        mark(page, "D_pagedown_burst_end")
        page.wait_for_timeout(500)

        # Pattern E: continuous slow scroll via setScrollTop in a loop
        mark(page, "E_smooth_scroll_start")
        page.evaluate("""
            async () => {
                var vp = document.querySelector('#matchesGrid .ag-body-viewport')
                    || document.querySelector('.ag-body-viewport');
                if (!vp) return;
                var target = vp.scrollTop + 1500;
                var sleep = ms => new Promise(r => setTimeout(r, ms));
                while (vp.scrollTop < target) {
                    vp.scrollTop += 30;
                    await sleep(40);
                }
            }
        """)
        mark(page, "E_smooth_scroll_end")
        page.wait_for_timeout(500)

        # Pattern F: PageUp back to top
        viewport.click()
        page.wait_for_timeout(150)
        mark(page, "F_pageup_burst_start")
        for _ in range(15):
            page.keyboard.press("PageUp")
            page.wait_for_timeout(160)
        mark(page, "F_pageup_burst_end")
        page.wait_for_timeout(600)

        trace = page.evaluate("() => window.__scrollTrace || null")
        try:
            video_path = page.video.path() if page.video else None
        except Exception:
            video_path = None
        context.close()
        browser.close()

        for _ in range(40):
            if video_path and Path(video_path).exists():
                break
            time.sleep(0.2)

        if video_path:
            video_path = Path(video_path)
            # Rename for clarity
            nice_video = VIDEO_DIR / f"auto_{stamp}.webm"
            try:
                video_path.rename(nice_video)
                video_path = nice_video
            except Exception:
                pass
            json_path = video_path.with_suffix(".trace.json")
        else:
            json_path = VIDEO_DIR / f"auto_{stamp}.trace.json"

        if trace is not None:
            json_path.write_text(json.dumps(trace, indent=2))

        print()
        print(f"Video : {video_path}")
        print(f"Trace : {json_path}")
        if trace:
            print(f"  scroll events  : {len(trace.get('scrollEvents', []))}")
            print(f"  row mutations  : {len(trace.get('mutations', []))}")
            print(f"  getRows fetches: {len(trace.get('getRowsCalls', []))}")
            print(f"  markers        : {len(trace.get('markers', []))}")


if __name__ == "__main__":
    main()

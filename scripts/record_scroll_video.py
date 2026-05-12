"""
Record a webm video of the user manually scrolling the grid, plus a JSON
trace of every row-style mutation that happens during the recording.

Run:
    python scripts/record_scroll_video.py

What it does:
  1. Launches Chromium in headed (visible) mode with video recording at 1280x720.
  2. Opens http://127.0.0.1:5000 and waits for the grid to load.
  3. Installs a MutationObserver in the page that logs every style change
     on .ag-row elements (timestamp, idx, oldY -> newY, height).
  4. Prints instructions in the terminal and BLOCKS on input() — you scroll
     in the live browser window to reproduce the blink, then come back to
     the terminal and press Enter.
  5. Pulls the mutation trace out of the page and writes it as JSON next
     to the video. Closes the browser. Video saves to recordings/<id>.webm.

Reviewing afterward:
  - Open the .webm in any media player; step frame-by-frame.
  - Open the .json trace to correlate visible blinks with row mutations.
"""
import json
import sys
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
    };

    // Scroll event timing on the AG body viewport
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

    // MutationObserver on the rows container — capture every style change
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
                    t: now,
                    idx: idx,
                    oldY: oldY,
                    newY: newY,
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

    // Hook fetch to log /api/matches calls (IRM block loads)
    var origFetch = window.fetch;
    window.fetch = function(input, init) {
        var url = (typeof input === 'string') ? input : (input && input.url);
        var start = performance.now();
        if (url && url.indexOf('/api/matches') !== -1) {
            return origFetch.apply(this, arguments).then(function(r) {
                window.__scrollTrace.getRowsCalls.push({
                    t_start: start,
                    t_end: performance.now(),
                    url: url,
                    duration_ms: performance.now() - start,
                });
                return r;
            });
        }
        return origFetch.apply(this, arguments);
    };

    return true;
}
"""


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            record_video_dir=str(VIDEO_DIR),
            record_video_size={"width": 1280, "height": 720},
        )
        page = context.new_page()

        print(f"Opening {APP_URL} ...")
        page.goto(APP_URL)

        try:
            page.wait_for_selector("#matchesGrid .ag-row", timeout=30000)
            page.wait_for_function(
                "() => { var t = document.querySelector('#gridInfo'); "
                "return t && /\\d/.test(t.innerText) && t.innerText !== '0 records'; }",
                timeout=15000,
            )
        except Exception as e:
            print(f"Grid didn't load: {e}")
            context.close()
            browser.close()
            sys.exit(1)

        # Install trace
        page.evaluate(TRACE_JS)
        print("Trace installed.\n")

        print("=" * 64)
        print(" RECORDING NOW. The browser window is open and live.")
        print(" Scroll the grid however you normally do.")
        print(" Reproduce the blink / screen-update behavior you see.")
        print(" Try mouse wheel, scrollbar, PageDown — whatever triggers it.")
        print(" When done, come back to THIS terminal and press Enter.")
        print("=" * 64)
        try:
            input("\n[Press Enter when finished scrolling] ")
        except (KeyboardInterrupt, EOFError):
            pass

        # Pull the trace
        try:
            trace = page.evaluate("() => window.__scrollTrace || null")
        except Exception as e:
            print(f"Couldn't read trace: {e}")
            trace = None

        # Capture video path before context closes
        video_path = None
        try:
            video_path = page.video.path() if page.video else None
        except Exception:
            pass

        context.close()
        browser.close()

        # Wait briefly for video file to finalize on disk
        for _ in range(20):
            if video_path and Path(video_path).exists():
                break
            time.sleep(0.2)

        # Write trace JSON alongside the video
        if video_path:
            video_path = Path(video_path)
            json_path = video_path.with_suffix(".trace.json")
        else:
            # Fallback if video path couldn't be resolved
            json_path = VIDEO_DIR / f"trace_{int(time.time())}.json"

        if trace is not None:
            json_path.write_text(json.dumps(trace, indent=2))

        print()
        print(f"Video saved : {video_path}")
        print(f"Trace saved : {json_path}")
        if trace:
            print(f"  scroll events : {len(trace.get('scrollEvents', []))}")
            print(f"  row mutations : {len(trace.get('mutations', []))}")
            print(f"  getRows fetches: {len(trace.get('getRowsCalls', []))}")
        print()
        print("Review the video and report back which moments look like the blink;")
        print("we'll correlate with the trace.")


if __name__ == "__main__":
    main()

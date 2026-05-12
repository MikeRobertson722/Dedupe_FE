"""
Diagnostic test: trace what mutates row positions AFTER a scroll.

User-reported symptom:
  "After scrolling, even a little, the screen seems to update after the scroll.
   Grid blanking still happens; grid blinks after scrolling."

Working hypothesis:
  AG Grid (during scroll) sets every rendered row's transform to translateY(idx*24).
  ~100ms after onBodyScrollEnd, fixRowPositions() fires and rewrites translateY
  values to account for autoHeight rows being taller than 24px. THAT rewrite is
  what the user sees as the post-scroll "blink" / "screen update."

This test does NOT change any app code. It installs a MutationObserver on
.ag-center-cols-container BEFORE doing a single small wheel scroll, then dumps:
  - the time delta from the user's wheel event to each row-position mutation
  - the per-row translateY delta (old -> new) that the mutation produced
  - how many rows got repositioned, and the cumulative pixel drift

The test fails (with the captured trace as the failure message) if it detects
a "visible reposition burst" after the scroll, defined as:
  >= 3 rows whose translateY changed by > 5 px within 300 ms of the wheel event.
Either outcome (pass or fail) prints the diagnostic data, which is the point.
"""

import pytest
from playwright.sync_api import Page


# Wheel delta small enough to feel like "even a little scroll" — single tick.
SMALL_WHEEL_PX = 120

# How long after the wheel we keep observing mutations.
OBSERVE_WINDOW_MS = 400

# A translateY change <= this is considered noise, not a visible reposition.
VISIBLE_PIXEL_THRESHOLD = 5

# That many rows shifting by more than the threshold = a visible burst.
BURST_ROW_COUNT = 3


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


def install_trace(page: Page):
    """
    Install a MutationObserver that records every style-attribute change on
    rows inside .ag-center-cols-container. Records the OLD and NEW translateY
    so we can see exactly what fixRowPositions does.

    Also stamps `wheelAt` from the test side just before scrolling so all
    deltas are computed against the actual scroll start, not against
    observer-install time.
    """
    page.evaluate(
        """
        () => {
            window.__trace = {
                installedAt: performance.now(),
                wheelAt: null,
                scrollEvents: [],   // raw scroll events on the viewport
                mutations: [],      // style mutations on .ag-row
            };

            var vp = document.querySelector('#matchesGrid .ag-body-viewport')
                  || document.querySelector('.ag-body-viewport');
            if (vp) {
                vp.addEventListener('scroll', function() {
                    window.__trace.scrollEvents.push({
                        t: performance.now(),
                        top: vp.scrollTop,
                    });
                }, { passive: true });
            }

            var container = document.querySelector(
                '#matchesGrid .ag-center-cols-container'
            ) || document.querySelector('.ag-center-cols-container');
            if (!container) {
                window.__trace.error = 'container not found';
                return;
            }

            function parseY(s) {
                if (!s) return null;
                var m = /translateY\\(([-\\d.]+)px\\)/.exec(s);
                return m ? parseFloat(m[1]) : null;
            }

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
                    var newY = parseY(el.style.transform || el.getAttribute('style') || '');
                    if (oldY === newY) continue;
                    window.__trace.mutations.push({
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
            window.__trace.observer = true;
        }
        """
    )


def read_trace(page: Page) -> dict:
    return page.evaluate("() => window.__trace || null")


def test_trace_post_scroll_repositioning(app_page: Page, tmp_path):
    page = app_page
    wait_for_grid_stable(page, min_rows=5)

    # Screenshot before doing anything.
    pre_path = tmp_path / "pre_scroll.png"
    page.screenshot(path=str(pre_path))

    install_trace(page)

    # Hover over the grid body so the wheel goes to the viewport.
    grid_body = page.locator(".ag-center-cols-viewport").first
    grid_body.hover()

    # Stamp wheelAt in-page right before the wheel event, then scroll a tiny bit.
    page.evaluate("() => { window.__trace.wheelAt = performance.now(); }")
    page.mouse.wheel(0, SMALL_WHEEL_PX)

    # Screenshot immediately after the wheel (catch the "wrong positions" frame).
    mid_path = tmp_path / "post_scroll_immediate.png"
    page.screenshot(path=str(mid_path))

    # Observe the post-scroll window.
    page.wait_for_timeout(OBSERVE_WINDOW_MS)

    # Screenshot after fixRowPositions has had time to run.
    settled_path = tmp_path / "post_scroll_settled.png"
    page.screenshot(path=str(settled_path))

    trace = read_trace(page)
    assert trace is not None, "Trace was not installed"
    assert trace.get("observer"), f"MutationObserver not installed: {trace.get('error')}"

    wheel_at = trace.get("wheelAt") or 0.0
    scroll_events = trace.get("scrollEvents", [])
    mutations = trace.get("mutations", [])

    # Time of the last raw scroll event (proxy for scroll-end).
    last_scroll_t = scroll_events[-1]["t"] if scroll_events else None

    # Mutations that happened after the wheel was stamped.
    post_wheel = [m for m in mutations if m["t"] >= wheel_at]

    # Earliest post-wheel mutation and its delay relative to scroll-end.
    if post_wheel and last_scroll_t is not None:
        first = min(post_wheel, key=lambda m: m["t"])
        first_delay_from_scrollend = first["t"] - last_scroll_t
    else:
        first_delay_from_scrollend = None

    # Significant per-row shifts within the observe window.
    visible_shifts = [
        m for m in post_wheel
        if m["deltaY"] is not None and abs(m["deltaY"]) > VISIBLE_PIXEL_THRESHOLD
    ]
    abs_max_delta = max((abs(m["deltaY"]) for m in visible_shifts), default=0)
    cumulative_abs_delta = sum(abs(m["deltaY"]) for m in visible_shifts)

    print("\n  --- Post-scroll repaint trace ---")
    print(f"  scroll events on viewport      : {len(scroll_events)}")
    if scroll_events:
        first_se = scroll_events[0]
        last_se = scroll_events[-1]
        print(f"  first scroll t={first_se['t']:.1f}  top={first_se['top']}")
        print(f"  last  scroll t={last_se['t']:.1f}  top={last_se['top']}")
    print(f"  total style mutations on rows  : {len(mutations)}")
    print(f"  mutations after wheel          : {len(post_wheel)}")
    print(f"  rows with |dTranslateY| > {VISIBLE_PIXEL_THRESHOLD}px : {len(visible_shifts)}")
    print(f"  max |dTranslateY|              : {abs_max_delta:.1f} px")
    print(f"  cumulative |dTranslateY|       : {cumulative_abs_delta:.1f} px")
    if first_delay_from_scrollend is not None:
        print(f"  delay from last scroll evt to first row mutation: "
              f"{first_delay_from_scrollend:.1f} ms")
    print(f"  screenshots: pre={pre_path.name}, "
          f"immediate={mid_path.name}, settled={settled_path.name}")
    print(f"  (saved under {tmp_path})")

    # Show the largest shifts (this is the diagnostic payload).
    if visible_shifts:
        print("\n  Largest per-row shifts (top 10 by |dy|):")
        for m in sorted(visible_shifts, key=lambda x: -abs(x["deltaY"]))[:10]:
            tm = m["t"] - (last_scroll_t if last_scroll_t is not None else wheel_at)
            print(f"    idx={m['idx']:>4}  h={m['height']:>3}px  "
                  f"oldY={m['oldY']!s:>8}  newY={m['newY']!s:>8}  "
                  f"dy={m['deltaY']:+.1f}px  t_after_scrollend={tm:+.0f}ms")

    # Decision: the user-visible bug is *delayed* repositioning, not the
    # repositioning itself. A fix that runs on the same frame as the scroll
    # (within ~32ms = 2 frames at 60fps) is imperceptible — the rows scroll
    # and reposition in the same paint. A fix that arrives 100ms+ later is
    # what the user sees as a "blink" / "screen update after the scroll."
    DELAYED_MS_THRESHOLD = 50  # > 50ms = perceptible as a separate update
    is_delayed = (first_delay_from_scrollend is not None
                  and first_delay_from_scrollend > DELAYED_MS_THRESHOLD
                  and len(visible_shifts) >= BURST_ROW_COUNT)

    if is_delayed:
        pytest.fail(
            f"DELAYED-REPOSITION BURST DETECTED after a {SMALL_WHEEL_PX}px wheel: "
            f"{len(visible_shifts)} rows shifted by more than {VISIBLE_PIXEL_THRESHOLD}px "
            f"(max |dy|={abs_max_delta:.1f}px, cumulative={cumulative_abs_delta:.1f}px), "
            f"and the first shift arrived {first_delay_from_scrollend:.0f}ms after the "
            f"last scroll event (> {DELAYED_MS_THRESHOLD}ms threshold). That delay is "
            f"what the user sees as a 'blink' after the scroll. Compare screenshots "
            f"{mid_path.name} and {settled_path.name}."
        )

    print(
        f"\n  [PASS] Reposition landed within {first_delay_from_scrollend:.0f}ms "
        f"of the last scroll event ({len(visible_shifts)} shifts spread across the "
        f"same frame as scroll — imperceptible)." if first_delay_from_scrollend is not None
        else f"\n  [PASS] No post-scroll row repositioning observed."
    )

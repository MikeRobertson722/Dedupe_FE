"""JS smoke test for the oversize-cell helpers in static/js/app.js.

The frontend functions `isOversize` and `oversizeTooltip` are pure given the
`STAGING_LIMITS` global. We extract them from app.js (so the test reflects
the live source, not a duplicated copy) and run them through Node with a
battery of assertions.

Skips cleanly if Node isn't on PATH so this test never blocks a Python-only
pytest run.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

APP_JS = Path(__file__).resolve().parents[2] / 'static' / 'js' / 'app.js'


def _extract_helpers() -> str:
    """Pull the relevant helper definitions out of app.js. We grab everything
    from the `var STAGING_LIMITS` declaration through the end of
    oversizeTooltip — a contiguous block in the file."""
    src = APP_JS.read_text(encoding='utf-8')
    start = src.index('var STAGING_LIMITS')
    end = src.index('// ── Staging length limits', start) if False else None
    # Grab the block: STAGING_LIMITS, loadStagingLimits, isOversize, oversizeTooltip.
    # Cheapest reliable cut: from `var STAGING_LIMITS` to the `}` that closes
    # `oversizeTooltip` (the one followed by a blank line).
    m = re.search(
        r'var STAGING_LIMITS[\s\S]+?function oversizeTooltip[\s\S]+?^\}',
        src, re.MULTILINE,
    )
    assert m, "Couldn't locate the staging-limits helpers in app.js"
    return m.group(0)


def _run_node(script: str) -> str:
    """Run `node -e <script>` and return stdout. Raises on non-zero exit."""
    proc = subprocess.run(
        ['node', '-e', script],
        capture_output=True, text=True, timeout=10,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"Node failed (exit {proc.returncode}):\n"
            f"--- stderr ---\n{proc.stderr}\n--- stdout ---\n{proc.stdout}"
        )
    return proc.stdout


@pytest.fixture(scope='module')
def helpers_js():
    if shutil.which('node') is None:
        pytest.skip("Node.js not installed — skipping JS helper smoke test")
    return _extract_helpers()


# Cases: (limits_dict, field, value, expect_oversize, tooltip_substring_or_None)
CASES = [
    # No limits loaded yet → never oversize, never tooltips.
    ({}, 'source_name', 'X' * 100, False, None),
    # Field not in the limits map → not oversize.
    ({'source_city': {'max': 40, 'staging_columns': ['ADDRCITY']}},
     'source_name', 'X' * 100, False, None),
    # Under the limit → not oversize.
    ({'source_name': {'max': 35, 'staging_columns': ['ADDRCONTACT']}},
     'source_name', 'X' * 30, False, None),
    # Exactly at the limit → not oversize (equality is fine).
    ({'source_name': {'max': 35, 'staging_columns': ['ADDRCONTACT']}},
     'source_name', 'X' * 35, False, None),
    # One over → oversize, tooltip mentions max and current count.
    ({'source_name': {'max': 35, 'staging_columns': ['ADDRCONTACT']}},
     'source_name', 'X' * 36, True, 'ADDRCONTACT'),
    # NULL value → not oversize even if limit is tiny.
    ({'source_name': {'max': 1, 'staging_columns': ['ADDRCONTACT']}},
     'source_name', None, False, None),
    # Empty string → length 0, not oversize.
    ({'source_name': {'max': 1, 'staging_columns': ['ADDRCONTACT']}},
     'source_name', '', False, None),
    # Auto-mirrored _2 sibling included in tooltip's staging_columns list.
    ({'source_address_recomend': {'max': 60,
        'staging_columns': ['ADDRADDRESS', 'ADDRADDRESS_2']}},
     'source_address_recomend', 'X' * 100, True, 'ADDRADDRESS_2'),
    # Numeric value coerced to string — length 5 ("99999"), should not
    # crash and should compare against max correctly.
    ({'source_zip': {'max': 5, 'staging_columns': ['ADDRZIPCODE']}},
     'source_zip', 999999, True, 'ADDRZIPCODE'),
]


def test_oversize_cases_table(helpers_js):
    """Run every case through Node and verify isOversize + oversizeTooltip."""
    cases_json = json.dumps([
        {'limits': lim, 'field': field, 'value': val,
         'expect_oversize': expect, 'tooltip_substr': substr}
        for (lim, field, val, expect, substr) in CASES
    ])
    script = f"""
    {helpers_js}
    const cases = {cases_json};
    let failed = 0;
    cases.forEach(function(c, i) {{
        STAGING_LIMITS = c.limits;
        const got = isOversize(c.field, c.value);
        const tip = oversizeTooltip(c.field, c.value);
        const oversizeOK = (got === c.expect_oversize);
        let tipOK = true;
        if (c.expect_oversize) {{
            tipOK = tip !== null && tip.indexOf(c.tooltip_substr) !== -1;
        }} else {{
            tipOK = (tip === null);
        }}
        if (!oversizeOK || !tipOK) {{
            failed++;
            console.error("Case " + i + " FAILED: " +
                JSON.stringify({{field: c.field, value: c.value,
                              got_oversize: got, want: c.expect_oversize,
                              got_tooltip: tip, want_substr: c.tooltip_substr}}));
        }}
    }});
    if (failed) {{ console.error("Total failures: " + failed); process.exit(1); }}
    console.log("All " + cases.length + " cases passed");
    """
    out = _run_node(script)
    assert 'All' in out and 'cases passed' in out, out


def test_tooltip_includes_actual_length(helpers_js):
    """The tooltip must quote BOTH the max and the current length so the user
    knows by how much they're over."""
    script = f"""
    {helpers_js}
    STAGING_LIMITS = {{ source_name: {{ max: 35, staging_columns: ['ADDRCONTACT'] }} }};
    const tip = oversizeTooltip('source_name', 'X'.repeat(47));
    if (!tip.includes('35') || !tip.includes('47')) {{
        console.error("Bad tooltip: " + tip);
        process.exit(1);
    }}
    console.log("OK");
    """
    assert _run_node(script).strip() == 'OK'


def test_isoversize_handles_undefined_limits_gracefully(helpers_js):
    """If STAGING_LIMITS hasn't been populated yet (e.g. /api/staging_limits
    failed or hasn't returned), the helper must still return false rather
    than throw."""
    script = f"""
    {helpers_js}
    STAGING_LIMITS = {{}};
    const got = isOversize('source_name', 'literally anything');
    if (got !== false) {{ console.error('Got: ' + got); process.exit(1); }}
    console.log("OK");
    """
    assert _run_node(script).strip() == 'OK'

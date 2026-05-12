"""
Regression: filter values must reset to 'All' on every page load.

Previously /api/grid_settings persisted filter_state (e.g. ssnFilter='yes')
and the client restored those values during initGrid. The result was the
grid showing 'N of M records' with N < M (often '496 of 1,538') after a
refresh, instead of showing all M records as expected.

Fix: client ignores filter_state during initGrid (passes null) and stops
writing filter_state via saveGridSetting. Column state is unaffected
(column order/width still persist across loads).

This test seeds the server-side filter_state with ssnFilter='yes', reloads
the page, and asserts:
  1. The SSN dropdown is at 'All' (empty value), not 'yes'.
  2. The grid-info text contains no 'X of Y' filtered form — it shows
     the total record count directly.
  3. After a user manually changes SSN to 'yes' in-session and then
     reloads, the filter still resets to 'All' (no in-session save either).
"""
import re
import pytest
import requests
from playwright.sync_api import Page


BASE_URL = "http://127.0.0.1:5000"


def _post_filter_state(filter_state: dict):
    r = requests.post(
        f"{BASE_URL}/api/grid_settings",
        json={"key": "filter_state", "value": filter_state},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def _get_saved_filter_state() -> dict:
    r = requests.get(f"{BASE_URL}/api/grid_settings", timeout=10)
    return (r.json() or {}).get("filter_state") or {}


def _wait_for_grid_loaded(page: Page):
    page.wait_for_selector("#matchesGrid .ag-row", timeout=30000)
    page.wait_for_function(
        "() => { var t = document.querySelector('#gridInfo'); "
        "return t && /\\d/.test(t.innerText) && t.innerText !== '0 records'; }",
        timeout=10000,
    )
    # Settle window: filter-state restoration races with the initial datasource
    # fire. If the fix is broken, the filter restore lands here.
    page.wait_for_timeout(900)


@pytest.fixture(scope="function")
def reset_filter_state_after():
    """Make sure the server-side filter_state is left empty after each test
    so other tests in the suite aren't affected by what this one seeded."""
    yield
    try:
        _post_filter_state({})
    except Exception:
        pass


def test_ssnFilter_yes_does_not_persist_across_page_load(app_page: Page, reset_filter_state_after):
    # Arrange: seed the server with the exact saved state that produced the bug.
    _post_filter_state({
        "activeRecFilter": "",
        "ssnFilter": "yes",
        "minNameScore": "",
        "maxNameScore": "",
        "minAddrScore": "",
        "maxAddrScore": "",
    })
    assert _get_saved_filter_state().get("ssnFilter") == "yes", \
        "Server didn't store the seeded filter_state"

    # Act: full page reload to exercise the load path.
    app_page.reload()
    _wait_for_grid_loaded(app_page)

    # Assert 1: SSN dropdown is back at 'All' (empty value).
    ssn_value = app_page.input_value("#ssnFilter")
    assert ssn_value == "", (
        f"With saved ssnFilter='yes' on the server, the SSN dropdown should "
        f"have reset to 'All' on reload (value='') — got value='{ssn_value}'. "
        f"Filter state is being restored when it shouldn't be."
    )

    # Assert 2: grid info shows the unfiltered count (no 'X of Y').
    info_text = (app_page.text_content("#gridInfo") or "").strip()
    assert " of " not in info_text, (
        f"Grid info should show the unfiltered record count (no 'X of Y'), "
        f"got: '{info_text}'. This is the user-visible '496 of 1,538' bug."
    )
    # Sanity: the number shown is non-zero and looks like a total.
    nums = re.findall(r"[\d,]+", info_text)
    assert nums and int(nums[0].replace(",", "")) > 0, \
        f"Grid info should contain a record count, got: '{info_text}'"


def test_in_session_ssn_change_does_not_persist_across_reload(app_page: Page, reset_filter_state_after):
    # Start fresh (no saved state).
    _post_filter_state({})

    _wait_for_grid_loaded(app_page)

    # Change SSN to 'yes' in the live page.
    app_page.select_option("#ssnFilter", "yes")
    app_page.wait_for_timeout(800)  # let the filter change + grid update fire

    # Reload — the filter should not have persisted.
    app_page.reload()
    _wait_for_grid_loaded(app_page)

    ssn_value = app_page.input_value("#ssnFilter")
    assert ssn_value == "", (
        f"After changing SSN to 'yes' in-session and reloading, the dropdown "
        f"should be back at 'All', got '{ssn_value}'. The change is being "
        f"persisted to the server when it shouldn't be."
    )

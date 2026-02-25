"""Custom wait conditions for AG Grid, modals, and animations."""
import re
from playwright.sync_api import Page


def wait_for_grid_ready(page: Page, timeout: int = 30000):
    """Wait for AG Grid to render rows."""
    page.wait_for_selector("#matchesGrid .ag-row", timeout=timeout)


def wait_for_grid_update(page: Page, timeout: int = 5000):
    """Wait briefly for AG Grid to re-render after a filter/sort change."""
    page.wait_for_timeout(500)


def wait_for_modal_visible(page: Page, modal_selector: str, timeout: int = 5000):
    """Wait for a Bootstrap modal to be fully shown."""
    page.wait_for_selector(f"{modal_selector}.show", state="visible", timeout=timeout)
    page.wait_for_timeout(400)  # Bootstrap animation


def wait_for_modal_hidden(page: Page, modal_selector: str, timeout: int = 5000):
    """Wait for a Bootstrap modal to be fully hidden."""
    page.wait_for_selector(f"{modal_selector}", state="hidden", timeout=timeout)


def wait_for_toast(page: Page, expected_text: str = None, timeout: int = 5000):
    """Wait for a toast notification to appear."""
    toast = page.wait_for_selector(".toast-msg", state="visible", timeout=timeout)
    if expected_text and toast:
        assert expected_text.lower() in toast.text_content().lower()
    return toast


def wait_for_sr_matches(page: Page, timeout: int = 5000):
    """Wait for search & replace auto-find debounce + render."""
    page.wait_for_timeout(600)


def wait_for_inline_save(page: Page, timeout: int = 3000):
    """Wait for an inline edit AJAX call to complete."""
    page.wait_for_timeout(500)


def get_grid_info_counts(page: Page):
    """Extract displayed and total record counts from grid info text.

    Parses 'Showing 2,345 of 10,051 records'
    Returns (displayed, total) tuple.
    """
    info_text = page.text_content("#gridInfo") or ""
    match = re.search(r'Showing ([\d,]+) of ([\d,]+)', info_text)
    if match:
        return (
            int(match.group(1).replace(',', '')),
            int(match.group(2).replace(',', ''))
        )
    return (0, 0)

"""Custom wait conditions for DataTables AJAX, modals, and animations."""
import re
from playwright.sync_api import Page


def wait_for_dt_reload(page: Page, timeout: int = 15000):
    """Wait for DataTable to complete an AJAX reload."""
    page.wait_for_function(
        """() => {
            const proc = document.querySelector('.dataTables_processing');
            return !proc || proc.style.display === 'none' ||
                   getComputedStyle(proc).display === 'none';
        }""",
        timeout=timeout
    )
    # Wait for either data rows or the "no data" row
    page.wait_for_selector("#matchesTable tbody tr", timeout=timeout)


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


def get_dt_records_filtered(page: Page) -> int:
    """Extract the filtered record count from DataTables info text.

    Parses 'Showing 1 to 100 of 10,051 entries' or
    'Showing 1 to 100 of 2,345 entries (filtered from 10,051 total entries)'
    """
    info_text = page.text_content("#matchesTable_info") or ""
    match = re.search(r'of ([\d,]+) entries', info_text)
    if match:
        return int(match.group(1).replace(',', ''))
    return 0

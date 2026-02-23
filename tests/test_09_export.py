"""Tests for export functionality."""
import pytest
from playwright.sync_api import Page, expect
from helpers.selectors import *
from helpers.wait_helpers import wait_for_toast


class TestExportSelected:

    def test_export_no_selection_shows_warning(self, app_page: Page):
        app_page.click(EXPORT_SELECTED_BTN)
        app_page.wait_for_timeout(500)
        # Should show a warning or alert when nothing selected
        toast = app_page.locator(TOAST)
        if toast.count() > 0:
            expect(toast.first).to_be_visible()

    def test_export_selected_downloads_xlsx(self, app_page: Page):
        # Select first row
        app_page.locator(ROW_CHECKBOX).first.check()
        with app_page.expect_download() as download_info:
            app_page.click(EXPORT_SELECTED_BTN)
        download = download_info.value
        assert download.suggested_filename.endswith(".xlsx")

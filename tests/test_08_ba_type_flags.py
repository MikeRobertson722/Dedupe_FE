"""Tests for JIB/Rev/Vendor checkbox toggles, deferred save, and import."""
import pytest
from playwright.sync_api import Page, expect
from helpers.selectors import *
from helpers.wait_helpers import wait_for_grid_update, wait_for_toast


class TestSingleFlagToggle:

    def _show_flag_columns(self, app_page: Page):
        """Make JIB/Rev/Vendor columns visible."""
        app_page.evaluate("() => gridApi.setColumnsVisible(['jib', 'rev', 'vendor'], true)")
        app_page.wait_for_timeout(300)

    @pytest.mark.destructive
    def test_jib_toggle_enables_save(self, app_page: Page):
        self._show_flag_columns(app_page)
        jib_cb = app_page.locator(".field-check[data-field='jib']").first
        jib_cb.click()
        app_page.wait_for_timeout(500)
        expect(app_page.locator(SAVE_CHANGES_BTN)).to_be_enabled()
        # Toggle back
        jib_cb.click()

    @pytest.mark.destructive
    def test_rev_toggle(self, app_page: Page):
        self._show_flag_columns(app_page)
        rev_cb = app_page.locator(".field-check[data-field='rev']").first
        rev_cb.click()
        app_page.wait_for_timeout(500)
        expect(app_page.locator(SAVE_CHANGES_BTN)).to_be_enabled()
        rev_cb.click()

    @pytest.mark.destructive
    def test_vendor_toggle(self, app_page: Page):
        self._show_flag_columns(app_page)
        vendor_cb = app_page.locator(".field-check[data-field='vendor']").first
        vendor_cb.click()
        app_page.wait_for_timeout(500)
        expect(app_page.locator(SAVE_CHANGES_BTN)).to_be_enabled()
        vendor_cb.click()


class TestSaveChanges:

    @pytest.mark.destructive
    def test_save_persists_and_disables_button(self, app_page: Page):
        app_page.evaluate("() => gridApi.setColumnsVisible(['jib'], true)")
        app_page.wait_for_timeout(300)
        jib_cb = app_page.locator(".field-check[data-field='jib']").first
        was_checked = jib_cb.is_checked()
        jib_cb.click()
        app_page.wait_for_timeout(500)

        app_page.click(SAVE_CHANGES_BTN)
        wait_for_toast(app_page, "Saved")
        app_page.wait_for_timeout(3000)
        expect(app_page.locator(SAVE_CHANGES_BTN)).to_be_disabled()

        # Restore original state
        jib_cb = app_page.locator(".field-check[data-field='jib']").first
        if jib_cb.is_checked() != was_checked:
            jib_cb.click()
            app_page.wait_for_timeout(500)
            app_page.click(SAVE_CHANGES_BTN)
            wait_for_toast(app_page)
            app_page.wait_for_timeout(3000)


class TestImportCSV:

    @pytest.mark.destructive
    def test_import_triggers_on_file_select(self, app_page: Page):
        app_page.select_option(IMPORT_TYPE_SELECT, "jib")
        import_input = app_page.locator(IMPORT_FILE_INPUT)
        import_input.set_input_files("tests/fixtures/test_import.csv")
        wait_for_toast(app_page, timeout=10000)

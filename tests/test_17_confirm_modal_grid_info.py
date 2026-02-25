"""Tests for confirm modal and grid info display."""
import pytest
from playwright.sync_api import Page, expect
from helpers.selectors import *
from helpers.wait_helpers import (
    wait_for_grid_update, wait_for_modal_visible, wait_for_modal_hidden,
    wait_for_toast, get_grid_info_counts
)
from helpers.api_helpers import api_get_record, api_get_stats, api_update_field


class TestConfirmModal:

    def _show_actions_column(self, app_page: Page):
        app_page.evaluate("() => gridApi.setColumnsVisible(['actions'], true)")
        app_page.wait_for_timeout(300)

    def test_confirm_shows_title_and_body(self, app_page: Page):
        self._show_actions_column(app_page)
        approve_btn = app_page.locator(
            "#matchesGrid .ag-row:first-child .btn-outline-success"
        ).first
        approve_btn.click()
        wait_for_modal_visible(app_page, CONFIRM_MODAL)
        expect(app_page.locator(CONFIRM_TITLE)).to_be_visible()
        expect(app_page.locator(CONFIRM_BODY)).to_be_visible()
        title_text = app_page.text_content(CONFIRM_TITLE)
        assert title_text and len(title_text.strip()) > 0
        # Dismiss without acting
        app_page.locator(CONFIRM_CANCEL_BTN).click()

    def test_confirm_cancel_dismisses(self, app_page: Page):
        self._show_actions_column(app_page)
        row_id = int(app_page.evaluate(
            "() => gridApi.getDisplayedRowAtIndex(0).data._row_id"
        ))
        original = api_get_record(row_id)

        approve_btn = app_page.locator(
            "#matchesGrid .ag-row:first-child .btn-outline-success"
        ).first
        approve_btn.click()
        wait_for_modal_visible(app_page, CONFIRM_MODAL)
        app_page.locator(CONFIRM_CANCEL_BTN).click()
        wait_for_modal_hidden(app_page, CONFIRM_MODAL)

        # Verify no change was made
        after = api_get_record(row_id)
        assert after['recommendation'] == original['recommendation']

    @pytest.mark.destructive
    def test_confirm_ok_triggers_callback(self, app_page: Page):
        self._show_actions_column(app_page)
        row_id = int(app_page.evaluate(
            "() => gridApi.getDisplayedRowAtIndex(0).data._row_id"
        ))
        original = api_get_record(row_id)

        approve_btn = app_page.locator(
            "#matchesGrid .ag-row:first-child .btn-outline-success"
        ).first
        approve_btn.click()
        wait_for_modal_visible(app_page, CONFIRM_MODAL)
        app_page.locator(CONFIRM_OK_BTN).click()
        wait_for_toast(app_page, "Approved")
        app_page.wait_for_timeout(1000)

        updated = api_get_record(row_id)
        assert updated['recommendation'] == "APPROVED"

        # Restore
        api_update_field(row_id, "recommendation", original.get('recommendation', ''))
        app_page.wait_for_timeout(3000)


class TestGridInfoDisplay:

    def test_grid_info_shows_on_load(self, app_page: Page):
        displayed, total = get_grid_info_counts(app_page)
        assert total > 0
        stats = api_get_stats()
        assert total == stats['total_records']

    def test_grid_info_updates_after_filter(self, app_page: Page):
        _, total = get_grid_info_counts(app_page)
        app_page.select_option(SSN_FILTER, "yes")
        wait_for_grid_update(app_page)
        displayed, _ = get_grid_info_counts(app_page)
        assert displayed < total

    def test_grid_info_updates_after_search(self, app_page: Page):
        _, total = get_grid_info_counts(app_page)
        app_page.fill(QUICK_FILTER_INPUT, "EXISTING BA")
        wait_for_grid_update(app_page)
        displayed, _ = get_grid_info_counts(app_page)
        assert displayed < total

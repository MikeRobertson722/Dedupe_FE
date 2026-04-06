"""Tests for immediate-save behavior (Save All button removed)."""
import pytest
from playwright.sync_api import Page, expect
from helpers.selectors import *
from helpers.wait_helpers import (
    wait_for_grid_update, wait_for_toast, wait_for_inline_save
)
from helpers.api_helpers import api_get_record, api_update_field


def _show_jib_column(app_page: Page):
    """Show JIB column and scroll it into view."""
    app_page.evaluate("() => gridApi.setColumnsVisible(['jib'], true)")
    app_page.wait_for_timeout(300)
    app_page.evaluate("() => gridApi.ensureColumnVisible('jib')")
    app_page.wait_for_timeout(500)


class TestImmediateSave:
    """Saves happen immediately without a Save All button."""

    def test_save_all_button_not_present(self, app_page: Page):
        """The Save All Changes button should not exist in the page."""
        assert app_page.locator('#saveChangesBtn').count() == 0

    def test_pending_count_badge_not_present(self, app_page: Page):
        """No pending-count badge should exist."""
        assert app_page.locator('.save-count').count() == 0

    @pytest.mark.destructive
    def test_inline_edit_shows_toast_immediately(self, app_page: Page):
        """An inline edit should show a Saved toast without clicking Save All."""
        _show_jib_column(app_page)

        row_id = int(app_page.evaluate(
            "() => gridApi.getDisplayedRowAtIndex(0).data._row_id"
        ))
        original = api_get_record(row_id)

        checkbox = app_page.locator(
            "#matchesGrid .ag-row:first-child .ag-cell[col-id='jib'] input"
        ).first
        checkbox.click()

        # Toast should appear — no Save All button needed
        wait_for_toast(app_page, timeout=10000)

        # Restore
        api_update_field(row_id, "jib", original.get('jib', 0))
        app_page.wait_for_timeout(1000)

    @pytest.mark.destructive
    def test_memo_edit_saves_immediately(self, app_page: Page):
        """Memo field edits save immediately."""
        app_page.evaluate("() => gridApi.setColumnsVisible(['memo'], true)")
        app_page.wait_for_timeout(300)
        app_page.evaluate("() => gridApi.ensureColumnVisible('memo')")
        app_page.wait_for_timeout(500)

        row_id = int(app_page.evaluate(
            "() => gridApi.getDisplayedRowAtIndex(0).data._row_id"
        ))
        original = api_get_record(row_id)

        app_page.evaluate(
            "() => document.querySelector('#matchesGrid .memo-text').click()"
        )
        app_page.wait_for_timeout(300)
        memo_input = app_page.locator("#matchesGrid .ag-cell[col-id='memo'] input").first
        memo_input.fill("SAVE_FLOW_TEST")
        memo_input.press("Enter")
        app_page.wait_for_timeout(1500)

        # Toast should appear without needing to click Save All
        wait_for_toast(app_page, timeout=10000)

        # After immediate save, grid should reflect the new value
        memo_val = app_page.evaluate(
            "(rid) => { var n = gridApi.getRowNode(String(rid)); return n ? n.data.memo : null; }",
            row_id
        )
        assert memo_val == "SAVE_FLOW_TEST"

        # Restore
        api_update_field(row_id, "memo", original.get('memo', ''))
        app_page.wait_for_timeout(1000)

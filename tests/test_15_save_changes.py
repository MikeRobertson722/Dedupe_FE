"""Tests for Save Changes button state and persistence flow."""
import re
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


def _click_jib_and_wait_pending(app_page: Page):
    """Click jib checkbox and wait for pending count to update."""
    checkbox = app_page.locator(
        "#matchesGrid .ag-row:first-child .ag-cell[col-id='jib'] input"
    ).first
    checkbox.click()
    wait_for_inline_save(app_page)
    # Wait for the save button to reflect the pending change
    expect(app_page.locator(SAVE_CHANGES_BTN)).to_be_enabled(timeout=10000)


class TestSaveButtonState:

    def test_save_disabled_initially(self, app_page: Page):
        expect(app_page.locator(SAVE_CHANGES_BTN)).to_be_disabled()

    @pytest.mark.destructive
    def test_save_shows_pending_count(self, app_page: Page):
        _show_jib_column(app_page)

        row_id = int(app_page.evaluate(
            "() => gridApi.getDisplayedRowAtIndex(0).data._row_id"
        ))
        original = api_get_record(row_id)

        _click_jib_and_wait_pending(app_page)

        badge_text = app_page.text_content(SAVE_COUNT_BADGE)
        assert badge_text and badge_text.strip() != ""
        assert "(" in badge_text

        # Restore
        api_update_field(row_id, "jib", original.get('jib', 0))
        app_page.wait_for_timeout(1000)

    @pytest.mark.destructive
    def test_save_enabled_after_edit(self, app_page: Page):
        _show_jib_column(app_page)

        row_id = int(app_page.evaluate(
            "() => gridApi.getDisplayedRowAtIndex(0).data._row_id"
        ))
        original = api_get_record(row_id)

        _click_jib_and_wait_pending(app_page)
        expect(app_page.locator(SAVE_CHANGES_BTN)).to_be_enabled()

        # Restore
        api_update_field(row_id, "jib", original.get('jib', 0))
        app_page.wait_for_timeout(1000)

    @pytest.mark.destructive
    def test_save_count_increments(self, app_page: Page):
        app_page.evaluate(
            "() => gridApi.setColumnsVisible(['jib', 'rev'], true)"
        )
        app_page.wait_for_timeout(300)
        app_page.evaluate("() => gridApi.ensureColumnVisible('jib')")
        app_page.wait_for_timeout(500)

        row_id_0 = int(app_page.evaluate(
            "() => gridApi.getDisplayedRowAtIndex(0).data._row_id"
        ))
        row_id_1 = int(app_page.evaluate(
            "() => gridApi.getDisplayedRowAtIndex(1).data._row_id"
        ))
        orig_0 = api_get_record(row_id_0)
        orig_1 = api_get_record(row_id_1)

        # First edit
        cb1 = app_page.locator(
            "#matchesGrid .ag-row:first-child .ag-cell[col-id='jib'] input"
        ).first
        cb1.click()
        wait_for_inline_save(app_page)
        expect(app_page.locator(SAVE_CHANGES_BTN)).to_be_enabled(timeout=10000)
        count1 = app_page.text_content(SAVE_COUNT_BADGE) or ""

        # Second edit on different row
        cb2 = app_page.locator(
            "#matchesGrid .ag-row:nth-child(2) .ag-cell[col-id='rev'] input"
        ).first
        cb2.click()
        wait_for_inline_save(app_page)
        app_page.wait_for_timeout(1000)
        count2 = app_page.text_content(SAVE_COUNT_BADGE) or ""

        # Extract numbers from "(N)" format
        nums1 = re.findall(r'\d+', count1)
        nums2 = re.findall(r'\d+', count2)
        n1 = int(nums1[0]) if nums1 else 0
        n2 = int(nums2[0]) if nums2 else 0
        assert n2 > n1

        # Restore
        api_update_field(row_id_0, "jib", orig_0.get('jib', 0))
        api_update_field(row_id_1, "rev", orig_1.get('rev', 0))
        app_page.wait_for_timeout(1000)


class TestSaveFlow:

    @pytest.mark.destructive
    def test_save_disables_during_ajax(self, app_page: Page):
        _show_jib_column(app_page)

        row_id = int(app_page.evaluate(
            "() => gridApi.getDisplayedRowAtIndex(0).data._row_id"
        ))
        original = api_get_record(row_id)

        _click_jib_and_wait_pending(app_page)

        # Click save and immediately check disabled state
        app_page.click(SAVE_CHANGES_BTN)
        expect(app_page.locator(SAVE_CHANGES_BTN)).to_be_disabled()

        # Wait for save to complete
        wait_for_toast(app_page, timeout=30000)
        app_page.wait_for_timeout(3000)

        # Restore
        api_update_field(row_id, "jib", original.get('jib', 0))
        app_page.wait_for_timeout(1000)

    @pytest.mark.destructive
    def test_save_refreshes_grid_data(self, app_page: Page):
        app_page.evaluate("() => gridApi.setColumnsVisible(['memo'], true)")
        app_page.wait_for_timeout(300)
        app_page.evaluate("() => gridApi.ensureColumnVisible('memo')")
        app_page.wait_for_timeout(500)

        row_id = int(app_page.evaluate(
            "() => gridApi.getDisplayedRowAtIndex(0).data._row_id"
        ))
        original = api_get_record(row_id)

        # Edit memo via browser click so the frontend AJAX path runs and
        # pendingCount increments — api_update_field bypasses the frontend entirely.
        app_page.evaluate(
            "() => document.querySelector('#matchesGrid .memo-text').click()"
        )
        app_page.wait_for_timeout(300)
        memo_input = app_page.locator("#matchesGrid .ag-cell[col-id='memo'] input").first
        memo_input.fill("SAVE_FLOW_TEST")
        memo_input.press("Enter")
        app_page.wait_for_timeout(1500)

        # Save button should now be enabled
        expect(app_page.locator(SAVE_CHANGES_BTN)).to_be_enabled(timeout=10000)
        app_page.click(SAVE_CHANGES_BTN)
        wait_for_toast(app_page, timeout=30000)
        app_page.wait_for_timeout(3000)

        # After save, grid should reflect the new value
        memo_val = app_page.evaluate(
            "(rid) => { var n = gridApi.getRowNode(String(rid)); return n ? n.data.memo : null; }",
            row_id
        )
        assert memo_val == "SAVE_FLOW_TEST"

        # Restore
        api_update_field(row_id, "memo", original.get('memo', ''))
        app_page.wait_for_timeout(1000)

    @pytest.mark.destructive
    def test_save_shows_success_toast(self, app_page: Page):
        _show_jib_column(app_page)

        row_id = int(app_page.evaluate(
            "() => gridApi.getDisplayedRowAtIndex(0).data._row_id"
        ))
        original = api_get_record(row_id)

        _click_jib_and_wait_pending(app_page)

        app_page.click(SAVE_CHANGES_BTN)
        # Toast says "Saved X record(s) to Snowflake"
        toast = wait_for_toast(app_page, timeout=30000)
        toast_text = toast.text_content().lower() if toast else ""
        assert "saved" in toast_text or "snowflake" in toast_text, \
            f"Expected success toast but got: {toast_text}"
        app_page.wait_for_timeout(3000)

        # Restore
        api_update_field(row_id, "jib", original.get('jib', 0))
        app_page.wait_for_timeout(1000)

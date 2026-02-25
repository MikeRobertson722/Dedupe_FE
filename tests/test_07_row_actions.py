"""Tests for edit modal, save, quick approve, and bulk approve."""
import pytest
from playwright.sync_api import Page, expect
from helpers.selectors import *
from helpers.wait_helpers import (
    wait_for_grid_update, wait_for_modal_visible, wait_for_modal_hidden, wait_for_toast
)
from helpers.api_helpers import api_get_record, api_update_field


class TestEditModal:

    def _show_actions_column(self, app_page: Page):
        """Make the Actions column visible via the Show/Hide dropdown."""
        app_page.locator(f"{COL_VIS_CONTAINER} button").click()
        # Actions is not in COL_DEFS so we use the grid API directly
        app_page.evaluate("() => gridApi.setColumnsVisible(['actions'], true)")
        app_page.wait_for_timeout(300)
        # Close dropdown
        app_page.locator(f"{COL_VIS_CONTAINER} button").click()

    def test_edit_button_opens_modal(self, app_page: Page):
        self._show_actions_column(app_page)
        edit_btn = app_page.locator("#matchesGrid .ag-row:first-child .btn-outline-primary").first
        edit_btn.click()
        wait_for_modal_visible(app_page, EDIT_MODAL)
        expect(app_page.locator(EDIT_MODAL)).to_be_visible()

    def test_canvas_section_is_readonly(self, app_page: Page):
        self._show_actions_column(app_page)
        app_page.locator("#matchesGrid .ag-row:first-child .btn-outline-primary").first.click()
        wait_for_modal_visible(app_page, EDIT_MODAL)
        canvas_name = app_page.locator(EDIT_CANVAS_NAME)
        expect(canvas_name).to_be_visible()
        tag = canvas_name.evaluate("el => el.tagName")
        assert tag.lower() == "td"

    def test_dec_fields_are_editable(self, app_page: Page):
        self._show_actions_column(app_page)
        app_page.locator("#matchesGrid .ag-row:first-child .btn-outline-primary").first.click()
        wait_for_modal_visible(app_page, EDIT_MODAL)
        dec_name = app_page.locator(EDIT_DEC_NAME)
        expect(dec_name).to_be_visible()
        expect(dec_name).to_be_editable()

    def test_modal_shows_scores(self, app_page: Page):
        self._show_actions_column(app_page)
        app_page.locator("#matchesGrid .ag-row:first-child .btn-outline-primary").first.click()
        wait_for_modal_visible(app_page, EDIT_MODAL)
        expect(app_page.locator(EDIT_SSN_MATCH)).to_be_visible()
        expect(app_page.locator(EDIT_NAME_SCORE)).to_be_visible()
        expect(app_page.locator(EDIT_ADDRESS_SCORE)).to_be_visible()

    def test_recommendation_dropdown_populated(self, app_page: Page):
        self._show_actions_column(app_page)
        app_page.locator("#matchesGrid .ag-row:first-child .btn-outline-primary").first.click()
        wait_for_modal_visible(app_page, EDIT_MODAL)
        options = app_page.locator(f"{EDIT_RECOMMENDATION} option")
        assert options.count() >= 2

    @pytest.mark.destructive
    def test_save_changes_persists(self, app_page: Page):
        self._show_actions_column(app_page)
        app_page.locator("#matchesGrid .ag-row:first-child .btn-outline-primary").first.click()
        wait_for_modal_visible(app_page, EDIT_MODAL)

        row_id = int(app_page.locator(EDIT_ROW_ID).input_value())
        original = api_get_record(row_id)

        app_page.fill(EDIT_DEC_NAME, "TEST_REGRESSION_NAME")
        app_page.click(EDIT_SAVE_BTN)
        wait_for_toast(app_page, timeout=10000)
        app_page.wait_for_timeout(3000)

        updated = api_get_record(row_id)
        assert updated['dec_name'] == "TEST_REGRESSION_NAME"

        # Restore
        api_update_field(row_id, "dec_name", original.get('dec_name', ''))
        app_page.wait_for_timeout(3000)


class TestQuickApprove:

    @pytest.mark.destructive
    def test_quick_approve(self, app_page: Page):
        # Show actions column
        app_page.evaluate("() => gridApi.setColumnsVisible(['actions'], true)")
        app_page.wait_for_timeout(300)

        row_id = int(app_page.evaluate(
            "() => gridApi.getDisplayedRowAtIndex(0).data._row_id"
        ))
        original = api_get_record(row_id)

        approve_btn = app_page.locator("#matchesGrid .ag-row:first-child .btn-outline-success").first
        approve_btn.click()
        app_page.locator(CONFIRM_OK_BTN).click()
        wait_for_toast(app_page, "Approved")
        app_page.wait_for_timeout(3000)

        updated = api_get_record(row_id)
        assert updated['recommendation'] == "APPROVED"

        # Restore
        api_update_field(row_id, "recommendation", original.get('recommendation', ''))
        app_page.wait_for_timeout(3000)


class TestBulkApprove:

    @pytest.mark.destructive
    def test_bulk_approve_selected(self, app_page: Page):
        cbs = app_page.locator(ROW_CHECKBOX)
        row_ids = []
        originals = {}
        for i in range(2):
            cbs.nth(i).click()
            rid = int(app_page.evaluate(
                "(idx) => gridApi.getDisplayedRowAtIndex(idx).data._row_id", i
            ))
            row_ids.append(rid)
            originals[rid] = api_get_record(rid)

        app_page.click(BULK_APPROVE_BTN)
        app_page.locator(CONFIRM_OK_BTN).click()
        wait_for_toast(app_page, "Approved")
        app_page.wait_for_timeout(3000)

        for rid in row_ids:
            updated = api_get_record(rid)
            assert updated['recommendation'] == "APPROVED"

        # Restore
        for rid, orig in originals.items():
            api_update_field(rid, "recommendation", orig.get('recommendation', ''))
        app_page.wait_for_timeout(3000)

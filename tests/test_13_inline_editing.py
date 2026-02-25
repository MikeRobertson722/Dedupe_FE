"""Tests for inline Process dropdown and Memo editing."""
import pytest
from playwright.sync_api import Page, expect
from helpers.selectors import *
from helpers.wait_helpers import (
    wait_for_grid_update, wait_for_toast, wait_for_inline_save
)
from helpers.api_helpers import api_get_record, api_update_field


class TestProcessInlineEdit:

    def _show_process_column(self, app_page: Page):
        app_page.evaluate(
            "() => gridApi.setColumnsVisible(['how_to_process'], true)"
        )
        app_page.wait_for_timeout(300)

    def test_process_cell_click_opens_editor(self, app_page: Page):
        self._show_process_column(app_page)
        cell = app_page.locator(
            f"#matchesGrid .ag-row:first-child {PROCESS_CELL}"
        ).first
        cell.click()
        app_page.wait_for_timeout(300)
        # AG Grid creates an edit wrapper with a select element
        editor = app_page.locator(
            f"#matchesGrid .ag-cell-edit-wrapper select, "
            f"#matchesGrid .ag-popup-editor select"
        )
        assert editor.count() > 0

    @pytest.mark.destructive
    def test_process_select_value_saves(self, app_page: Page):
        self._show_process_column(app_page)

        row_id = int(app_page.evaluate(
            "() => gridApi.getDisplayedRowAtIndex(0).data._row_id"
        ))
        original = api_get_record(row_id)

        cell = app_page.locator(
            f"#matchesGrid .ag-row:first-child {PROCESS_CELL}"
        ).first
        cell.click()
        app_page.wait_for_timeout(300)

        # Select a specific value
        editor = app_page.locator(
            f"#matchesGrid .ag-cell-edit-wrapper select, "
            f"#matchesGrid .ag-popup-editor select"
        ).first
        editor.select_option("Manual Review - DNP")
        # Click elsewhere to confirm
        app_page.locator(GRID).click(position={"x": 5, "y": 5})
        wait_for_inline_save(app_page)
        app_page.wait_for_timeout(1000)

        updated = api_get_record(row_id)
        assert updated['how_to_process'] == "Manual Review - DNP"

        # Restore
        api_update_field(
            row_id, "how_to_process",
            original.get('how_to_process', '')
        )
        app_page.wait_for_timeout(1000)

    def test_process_dropdown_has_4_options(self, app_page: Page):
        self._show_process_column(app_page)
        cell = app_page.locator(
            f"#matchesGrid .ag-row:first-child {PROCESS_CELL}"
        ).first
        cell.click()
        app_page.wait_for_timeout(300)

        options = app_page.locator(
            f"#matchesGrid .ag-cell-edit-wrapper select option, "
            f"#matchesGrid .ag-popup-editor select option"
        )
        assert options.count() == 4

    @pytest.mark.destructive
    def test_process_bulk_edit_shift_select(self, app_page: Page):
        self._show_process_column(app_page)

        # Capture original values for first 3 rows
        originals = {}
        for i in range(3):
            rid = int(app_page.evaluate(
                "(idx) => gridApi.getDisplayedRowAtIndex(idx).data._row_id", i
            ))
            originals[rid] = api_get_record(rid)

        # Click first process cell, shift-click third
        first_cell = app_page.locator(
            f"#matchesGrid .ag-row:first-child {PROCESS_CELL}"
        ).first
        first_cell.click()
        app_page.wait_for_timeout(200)

        third_cell = app_page.locator(
            f"#matchesGrid .ag-row:nth-child(3) {PROCESS_CELL}"
        ).first
        third_cell.click(modifiers=["Shift"])
        app_page.wait_for_timeout(200)

        # Now click to edit the first cell
        first_cell.click()
        app_page.wait_for_timeout(300)

        editor = app_page.locator(
            f"#matchesGrid .ag-cell-edit-wrapper select, "
            f"#matchesGrid .ag-popup-editor select"
        ).first
        editor.select_option("Merge BA and address")
        app_page.locator(GRID).click(position={"x": 5, "y": 5})
        app_page.wait_for_timeout(2000)

        # Check if at least the first row was updated
        first_rid = list(originals.keys())[0]
        updated = api_get_record(first_rid)
        assert updated['how_to_process'] == "Merge BA and address"

        # Restore all
        for rid, orig in originals.items():
            api_update_field(
                rid, "how_to_process",
                orig.get('how_to_process', '')
            )
        app_page.wait_for_timeout(1000)


class TestProcessContextMenu:

    def _show_process_column(self, app_page: Page):
        app_page.evaluate(
            "() => gridApi.setColumnsVisible(['how_to_process'], true)"
        )
        app_page.wait_for_timeout(300)

    def test_right_click_header_shows_menu(self, app_page: Page):
        self._show_process_column(app_page)
        header = app_page.locator(
            ".ag-header-cell[col-id='how_to_process']"
        ).first
        header.click(button="right")
        app_page.wait_for_timeout(300)

        menu = app_page.locator(PROCESS_CTX_MENU)
        assert menu.count() > 0
        items = app_page.locator(PROCESS_CTX_ITEM)
        assert items.count() == 4

        # Dismiss by clicking elsewhere
        app_page.locator("body").click()

    @pytest.mark.destructive
    def test_context_menu_sets_all_visible(self, app_page: Page):
        self._show_process_column(app_page)

        # Capture a sample of original values
        sample_ids = []
        for i in range(min(3, int(app_page.evaluate(
            "() => gridApi.getDisplayedRowCount()"
        )))):
            rid = int(app_page.evaluate(
                "(idx) => gridApi.getDisplayedRowAtIndex(idx).data._row_id", i
            ))
            sample_ids.append(rid)
        originals = {rid: api_get_record(rid) for rid in sample_ids}

        header = app_page.locator(
            ".ag-header-cell[col-id='how_to_process']"
        ).first
        header.click(button="right")
        app_page.wait_for_timeout(300)

        # Click the last menu item (Manual Review - DNP)
        items = app_page.locator(PROCESS_CTX_ITEM)
        items.last.click()
        app_page.wait_for_timeout(3000)

        # Verify at least one row was updated
        updated = api_get_record(sample_ids[0])
        assert updated['how_to_process'] != ""

        # Restore
        for rid, orig in originals.items():
            api_update_field(
                rid, "how_to_process",
                orig.get('how_to_process', '')
            )
        app_page.wait_for_timeout(1000)


class TestMemoInlineEdit:

    def _show_memo_column(self, app_page: Page):
        app_page.evaluate("() => gridApi.setColumnsVisible(['memo'], true)")
        app_page.wait_for_timeout(300)

    def test_memo_click_opens_input(self, app_page: Page):
        self._show_memo_column(app_page)
        memo = app_page.locator(f"#matchesGrid {MEMO_TEXT}").first
        memo.click()
        app_page.wait_for_timeout(300)

        # Should now have an input within the memo cell
        memo_input = app_page.locator(
            "#matchesGrid .ag-cell[col-id='memo'] input"
        )
        assert memo_input.count() > 0

    @pytest.mark.destructive
    def test_memo_enter_saves_value(self, app_page: Page):
        self._show_memo_column(app_page)

        row_id = int(app_page.evaluate(
            "() => gridApi.getDisplayedRowAtIndex(0).data._row_id"
        ))
        original = api_get_record(row_id)

        memo = app_page.locator(f"#matchesGrid {MEMO_TEXT}").first
        memo.click()
        app_page.wait_for_timeout(300)

        memo_input = app_page.locator(
            "#matchesGrid .ag-cell[col-id='memo'] input"
        ).first
        memo_input.fill("TEST_MEMO_ENTER")
        memo_input.press("Enter")
        wait_for_inline_save(app_page)
        app_page.wait_for_timeout(1000)

        updated = api_get_record(row_id)
        assert updated['memo'] == "TEST_MEMO_ENTER"

        # Restore
        api_update_field(row_id, "memo", original.get('memo', ''))
        app_page.wait_for_timeout(1000)

    def test_memo_escape_cancels_edit(self, app_page: Page):
        self._show_memo_column(app_page)

        row_id = int(app_page.evaluate(
            "() => gridApi.getDisplayedRowAtIndex(0).data._row_id"
        ))
        original = api_get_record(row_id)

        memo = app_page.locator(f"#matchesGrid {MEMO_TEXT}").first
        memo.click()
        app_page.wait_for_timeout(300)

        memo_input = app_page.locator(
            "#matchesGrid .ag-cell[col-id='memo'] input"
        ).first
        memo_input.fill("SHOULD_NOT_SAVE")
        memo_input.press("Escape")
        app_page.wait_for_timeout(500)

        after = api_get_record(row_id)
        assert after['memo'] == original.get('memo', '')

    @pytest.mark.destructive
    def test_memo_blur_saves_value(self, app_page: Page):
        self._show_memo_column(app_page)

        row_id = int(app_page.evaluate(
            "() => gridApi.getDisplayedRowAtIndex(0).data._row_id"
        ))
        original = api_get_record(row_id)

        memo = app_page.locator(f"#matchesGrid {MEMO_TEXT}").first
        memo.click()
        app_page.wait_for_timeout(300)

        memo_input = app_page.locator(
            "#matchesGrid .ag-cell[col-id='memo'] input"
        ).first
        memo_input.fill("TEST_MEMO_BLUR")
        # Click elsewhere to trigger blur
        app_page.locator(GRID).click(position={"x": 5, "y": 5})
        wait_for_inline_save(app_page)
        app_page.wait_for_timeout(1000)

        updated = api_get_record(row_id)
        assert updated['memo'] == "TEST_MEMO_BLUR"

        # Restore
        api_update_field(row_id, "memo", original.get('memo', ''))
        app_page.wait_for_timeout(1000)

    @pytest.mark.destructive
    def test_memo_value_persists_after_refresh(self, app_page: Page):
        self._show_memo_column(app_page)

        row_id = int(app_page.evaluate(
            "() => gridApi.getDisplayedRowAtIndex(0).data._row_id"
        ))
        original = api_get_record(row_id)

        memo = app_page.locator(f"#matchesGrid {MEMO_TEXT}").first
        memo.click()
        app_page.wait_for_timeout(300)

        memo_input = app_page.locator(
            "#matchesGrid .ag-cell[col-id='memo'] input"
        ).first
        memo_input.fill("TEST_MEMO_PERSIST")
        memo_input.press("Enter")
        wait_for_inline_save(app_page)
        app_page.wait_for_timeout(1000)

        # Trigger grid refresh
        app_page.evaluate("() => refreshGridData()")
        app_page.wait_for_timeout(2000)

        # Re-show memo column after refresh
        self._show_memo_column(app_page)
        memo_val = app_page.evaluate(
            "(rid) => { var n = gridApi.getDisplayedRowAtIndex(0); "
            "return n ? n.data.memo : ''; }",
            row_id
        )
        assert memo_val == "TEST_MEMO_PERSIST"

        # Restore
        api_update_field(row_id, "memo", original.get('memo', ''))
        app_page.wait_for_timeout(1000)

    @pytest.mark.destructive
    def test_memo_pushes_to_undo_stack(self, app_page: Page):
        self._show_memo_column(app_page)

        row_id = int(app_page.evaluate(
            "() => gridApi.getDisplayedRowAtIndex(0).data._row_id"
        ))
        original = api_get_record(row_id)

        memo = app_page.locator(f"#matchesGrid {MEMO_TEXT}").first
        memo.click()
        app_page.wait_for_timeout(300)

        memo_input = app_page.locator(
            "#matchesGrid .ag-cell[col-id='memo'] input"
        ).first
        memo_input.fill("UNDO_TEST_MEMO")
        memo_input.press("Enter")
        wait_for_inline_save(app_page)
        app_page.wait_for_timeout(500)

        expect(app_page.locator(UNDO_BTN)).to_be_enabled()

        # Restore via undo
        app_page.keyboard.press("Control+z")
        app_page.wait_for_timeout(2000)

        # Also restore via API just in case
        api_update_field(row_id, "memo", original.get('memo', ''))
        app_page.wait_for_timeout(1000)

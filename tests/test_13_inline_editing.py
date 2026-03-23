"""Tests for inline Process dropdown and Memo editing."""
import pytest
from playwright.sync_api import Page, expect
from helpers.selectors import *
from helpers.wait_helpers import (
    wait_for_grid_update, wait_for_toast, wait_for_inline_save
)
from helpers.api_helpers import (
    api_get_record, api_update_field, api_get_db_record
)


class TestProcessInlineEdit:

    def _show_process_column(self, app_page: Page):
        app_page.evaluate(
            "() => gridApi.setColumnsVisible(['how_to_process'], true)"
        )
        app_page.wait_for_timeout(300)
        app_page.evaluate("() => gridApi.ensureColumnVisible('how_to_process')")
        app_page.wait_for_timeout(500)

    def _select_process_value(self, app_page: Page, row_index: int, option_text: str):
        """Select a value from the native <select> in the Process cell."""
        app_page.evaluate(
            """(args) => {
                var sel = document.querySelectorAll('#matchesGrid .process-select')[args.idx];
                if (sel) {
                    sel.value = args.val;
                    sel.dispatchEvent(new Event('change', { bubbles: true }));
                }
            }""",
            {"idx": row_index, "val": option_text}
        )
        app_page.wait_for_timeout(500)

    def test_process_cell_has_native_select(self, app_page: Page):
        self._show_process_column(app_page)
        select = app_page.locator("#matchesGrid .process-select").first
        expect(select).to_be_visible()

    def test_process_dropdown_has_options(self, app_page: Page):
        self._show_process_column(app_page)
        options = app_page.locator(
            "#matchesGrid .process-select >> nth=0 >> option"
        )
        # 4 process options + 1 blank option = 5
        assert options.count() == 5

    @pytest.mark.destructive
    def test_process_select_value_saves(self, app_page: Page):
        """Change process via native select and verify in-memory update."""
        self._show_process_column(app_page)

        row_id = int(app_page.evaluate(
            "() => gridApi.getDisplayedRowAtIndex(0).data._row_id"
        ))
        original = api_get_record(row_id)

        self._select_process_value(app_page, 0, "Manual Review - DNP")
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

    @pytest.mark.destructive
    def test_process_change_enables_save_button(self, app_page: Page):
        """Changing process must enable the Save Changes button with pending count."""
        self._show_process_column(app_page)

        row_id = int(app_page.evaluate(
            "() => gridApi.getDisplayedRowAtIndex(0).data._row_id"
        ))
        original = api_get_record(row_id)

        # Choose a target value that differs from the current value so the
        # change handler doesn't short-circuit on oldValue === newValue.
        current_val = original.get('how_to_process', '')
        target_val = "Manual Review - DNP" if current_val != "Manual Review - DNP" else "Add new BA and address"

        # Save button should be disabled initially (or show existing pending count)
        self._select_process_value(app_page, 0, target_val)
        wait_for_inline_save(app_page)

        # Save button should now be enabled
        expect(app_page.locator(SAVE_CHANGES_BTN)).to_be_enabled(timeout=10000)

        # Badge should show a count
        badge_text = app_page.text_content(SAVE_COUNT_BADGE) or ""
        assert "(" in badge_text, f"Expected pending count badge but got: {badge_text}"

        # Restore
        api_update_field(
            row_id, "how_to_process",
            original.get('how_to_process', '')
        )
        app_page.wait_for_timeout(1000)

    @pytest.mark.destructive
    def test_process_change_save_and_verify_db_by_uid(self, app_page: Page):
        """Full end-to-end: change process -> save changes -> query DB by UID to verify."""
        self._show_process_column(app_page)
        # Also show UID column so we can read it
        app_page.evaluate(
            "() => gridApi.setColumnsVisible(['uid'], true)"
        )
        app_page.wait_for_timeout(300)

        row_id = int(app_page.evaluate(
            "() => gridApi.getDisplayedRowAtIndex(0).data._row_id"
        ))
        uid = app_page.evaluate(
            "() => gridApi.getDisplayedRowAtIndex(0).data.id"
        )
        original = api_get_record(row_id)

        # Choose a target value that differs from the current value so the
        # change handler doesn't short-circuit on oldValue === newValue.
        current_val = original.get('how_to_process', '')
        target_val = "Manual Review - DNP" if current_val != "Manual Review - DNP" else "Add new BA and address"

        # Step 1: Change the process value
        self._select_process_value(app_page, 0, target_val)
        wait_for_inline_save(app_page)

        # Step 2: Verify save button is enabled
        expect(app_page.locator(SAVE_CHANGES_BTN)).to_be_enabled(timeout=10000)

        # Step 3: Verify in-memory update happened
        mem_record = api_get_record(row_id)
        assert mem_record['how_to_process'] == target_val, \
            f"In-memory how_to_process expected '{target_val}', got '{mem_record['how_to_process']}'"

        # Step 4: Click Save Changes to persist to Snowflake
        app_page.click(SAVE_CHANGES_BTN)
        toast = wait_for_toast(app_page, timeout=30000)
        toast_text = toast.text_content().lower() if toast else ""
        assert "saved" in toast_text or "snowflake" in toast_text, \
            f"Expected save success toast but got: {toast_text}"
        app_page.wait_for_timeout(3000)

        # Step 5: Query database directly by UID to verify persistence
        db_record = api_get_db_record(int(uid))
        db_process = db_record.get('how_to_process', '')
        assert db_process == target_val, \
            f"Database HOW_TO_PROCESS for UID={uid} expected '{target_val}', got '{db_process}'"

        # Step 6: Save button should be disabled after successful save
        expect(app_page.locator(SAVE_CHANGES_BTN)).to_be_disabled(timeout=10000)

        # Restore original value via browser (so JS pendingCount updates)
        orig_process = original.get('how_to_process', '')
        if orig_process:
            self._select_process_value(app_page, 0, orig_process)
        else:
            self._select_process_value(app_page, 0, "")
        wait_for_inline_save(app_page)
        expect(app_page.locator(SAVE_CHANGES_BTN)).to_be_enabled(timeout=10000)
        app_page.click(SAVE_CHANGES_BTN)
        wait_for_toast(app_page, timeout=30000)
        app_page.wait_for_timeout(3000)

    @pytest.mark.destructive
    def test_process_updates_grid_data_model(self, app_page: Page):
        """Verify the AG Grid data model is updated when process changes."""
        self._show_process_column(app_page)

        row_id = int(app_page.evaluate(
            "() => gridApi.getDisplayedRowAtIndex(0).data._row_id"
        ))
        original = api_get_record(row_id)

        self._select_process_value(app_page, 0, "Add address to existing BA")
        wait_for_inline_save(app_page)
        app_page.wait_for_timeout(500)

        # Check AG Grid data model directly
        grid_value = app_page.evaluate(
            "() => gridApi.getDisplayedRowAtIndex(0).data.how_to_process"
        )
        assert grid_value == "Add address to existing BA", \
            f"Grid data model expected 'Add address to existing BA', got '{grid_value}'"

        # Restore
        api_update_field(
            row_id, "how_to_process",
            original.get('how_to_process', '')
        )
        app_page.wait_for_timeout(1000)

    @pytest.mark.destructive
    def test_process_pushes_to_undo_stack(self, app_page: Page):
        """Changing process should push to undo stack."""
        self._show_process_column(app_page)

        row_id = int(app_page.evaluate(
            "() => gridApi.getDisplayedRowAtIndex(0).data._row_id"
        ))
        original = api_get_record(row_id)

        # Choose a target value that differs from the current value so the
        # change handler doesn't short-circuit on oldValue === newValue.
        current_val = original.get('how_to_process', '')
        target_val = "Manual Review - DNP" if current_val != "Manual Review - DNP" else "Add new BA and address"

        self._select_process_value(app_page, 0, target_val)
        wait_for_inline_save(app_page)
        app_page.wait_for_timeout(500)

        expect(app_page.locator(UNDO_BTN)).to_be_enabled()

        # Restore via undo
        app_page.keyboard.press("Control+z")
        app_page.wait_for_timeout(3000)

        # Also restore via API just in case
        api_update_field(
            row_id, "how_to_process",
            original.get('how_to_process', '')
        )
        app_page.wait_for_timeout(1000)

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

        # Click first process cell, shift-click third to select range
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

        # Change the first row's select — should apply to all selected
        self._select_process_value(app_page, 0, "Merge BA and address")
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
        app_page.evaluate("() => gridApi.ensureColumnVisible('how_to_process')")
        app_page.wait_for_timeout(500)

    @pytest.mark.skip(reason="Process context menu not yet implemented")
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

    @pytest.mark.skip(reason="Process context menu not yet implemented")
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
        app_page.evaluate("() => gridApi.ensureColumnVisible('memo')")
        app_page.wait_for_timeout(500)
        # Scroll the memo cell into the viewport
        app_page.locator("#matchesGrid .ag-cell[col-id='memo']").first.scroll_into_view_if_needed()
        app_page.wait_for_timeout(300)

    def test_memo_click_opens_input(self, app_page: Page):
        self._show_memo_column(app_page)
        # Trigger the .memo-text click handler via JS
        # (the span may be empty/zero-size, so Playwright click fails on visibility)
        app_page.evaluate(
            "() => document.querySelector('#matchesGrid .memo-text').click()"
        )
        app_page.wait_for_timeout(500)

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

        # Trigger the .memo-text click handler via JS
        # (the span may be empty/zero-size, so Playwright click fails on visibility)
        app_page.evaluate(
            "() => document.querySelector('#matchesGrid .memo-text').click()"
        )
        app_page.wait_for_timeout(500)

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

        # Trigger the .memo-text click handler via JS
        # (the span may be empty/zero-size, so Playwright click fails on visibility)
        app_page.evaluate(
            "() => document.querySelector('#matchesGrid .memo-text').click()"
        )
        app_page.wait_for_timeout(500)

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

        # Trigger the .memo-text click handler via JS
        # (the span may be empty/zero-size, so Playwright click fails on visibility)
        app_page.evaluate(
            "() => document.querySelector('#matchesGrid .memo-text').click()"
        )
        app_page.wait_for_timeout(500)

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

        # Trigger the .memo-text click handler via JS
        # (the span may be empty/zero-size, so Playwright click fails on visibility)
        app_page.evaluate(
            "() => document.querySelector('#matchesGrid .memo-text').click()"
        )
        app_page.wait_for_timeout(500)

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

        # Trigger the .memo-text click handler via JS
        # (the span may be empty/zero-size, so Playwright click fails on visibility)
        app_page.evaluate(
            "() => document.querySelector('#matchesGrid .memo-text').click()"
        )
        app_page.wait_for_timeout(500)

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
        app_page.wait_for_timeout(3000)

        # Also restore via API just in case
        api_update_field(row_id, "memo", original.get('memo', ''))
        app_page.wait_for_timeout(1000)

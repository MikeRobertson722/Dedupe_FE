"""Tests for undo/redo stack system."""
import pytest
from playwright.sync_api import Page, expect
from helpers.selectors import *
from helpers.wait_helpers import (
    wait_for_grid_update, wait_for_toast, wait_for_inline_save
)
from helpers.api_helpers import api_get_record, api_update_field


# Undo/redo AJAX calls take variable time.
UNDO_TIMEOUT = 15000


def _show_jib_column(app_page: Page):
    """Show JIB column and scroll it into view."""
    app_page.evaluate("() => gridApi.setColumnsVisible(['jib'], true)")
    app_page.wait_for_timeout(300)
    app_page.evaluate("() => gridApi.ensureColumnVisible('jib')")
    app_page.wait_for_timeout(500)


def _show_flag_columns(app_page: Page):
    """Show JIB/Rev/Vendor columns and scroll them into view."""
    app_page.evaluate(
        "() => gridApi.setColumnsVisible(['jib', 'rev', 'vendor'], true)"
    )
    app_page.wait_for_timeout(300)
    app_page.evaluate("() => gridApi.ensureColumnVisible('jib')")
    app_page.wait_for_timeout(500)


def _click_jib_and_wait(app_page: Page):
    """Click jib checkbox and wait for inline save AJAX."""
    checkbox = app_page.locator(
        "#matchesGrid .ag-row:first-child .ag-cell[col-id='jib'] input"
    ).first
    checkbox.click()
    wait_for_inline_save(app_page)
    # Wait for undo button to enable (signals the change was registered)
    expect(app_page.locator(UNDO_BTN)).to_be_enabled(timeout=10000)


def _undo_and_wait(app_page: Page, row_id: int, field: str, expected_value):
    """Perform undo and wait for the API to reflect the reverted value."""
    app_page.keyboard.press("Control+z")
    # Poll the API until the value reverts (max ~15s)
    app_page.wait_for_function(
        """([rid, fld, expected]) => {
            return new Promise(resolve => {
                fetch('/api/record/' + rid)
                    .then(r => r.json())
                    .then(data => resolve(String(data[fld]) === String(expected)))
                    .catch(() => resolve(false));
            });
        }""",
        arg=[row_id, field, expected_value],
        timeout=UNDO_TIMEOUT
    )
    app_page.wait_for_timeout(300)


def _redo_and_wait(app_page: Page, row_id: int, field: str, expected_value):
    """Perform redo and wait for the API to reflect the re-applied value."""
    app_page.keyboard.press("Control+y")
    app_page.wait_for_function(
        """([rid, fld, expected]) => {
            return new Promise(resolve => {
                fetch('/api/record/' + rid)
                    .then(r => r.json())
                    .then(data => resolve(String(data[fld]) === String(expected)))
                    .catch(() => resolve(false));
            });
        }""",
        arg=[row_id, field, expected_value],
        timeout=UNDO_TIMEOUT
    )
    app_page.wait_for_timeout(300)


class TestUndoRedoButtonStates:

    def test_undo_disabled_initially(self, app_page: Page):
        expect(app_page.locator(UNDO_BTN)).to_be_disabled()

    def test_redo_disabled_initially(self, app_page: Page):
        expect(app_page.locator(REDO_BTN)).to_be_disabled()

    @pytest.mark.destructive
    def test_undo_enabled_after_change(self, app_page: Page):
        _show_jib_column(app_page)

        row_id = int(app_page.evaluate(
            "() => gridApi.getDisplayedRowAtIndex(0).data._row_id"
        ))
        original = api_get_record(row_id)

        _click_jib_and_wait(app_page)
        expect(app_page.locator(UNDO_BTN)).to_be_enabled()

        # Restore
        _undo_and_wait(app_page, row_id, "jib", original.get('jib', 0))
        api_update_field(row_id, "jib", original.get('jib', 0))
        app_page.wait_for_timeout(500)

    @pytest.mark.destructive
    def test_redo_enabled_after_undo(self, app_page: Page):
        _show_jib_column(app_page)

        row_id = int(app_page.evaluate(
            "() => gridApi.getDisplayedRowAtIndex(0).data._row_id"
        ))
        original = api_get_record(row_id)
        orig_jib = original.get('jib', 0)

        _click_jib_and_wait(app_page)

        _undo_and_wait(app_page, row_id, "jib", orig_jib)
        expect(app_page.locator(REDO_BTN)).to_be_enabled()

        # Restore
        api_update_field(row_id, "jib", orig_jib)
        app_page.wait_for_timeout(500)

    @pytest.mark.destructive
    def test_redo_disabled_after_new_change(self, app_page: Page):
        _show_flag_columns(app_page)

        row_id = int(app_page.evaluate(
            "() => gridApi.getDisplayedRowAtIndex(0).data._row_id"
        ))
        original = api_get_record(row_id)
        orig_jib = original.get('jib', 0)

        # Change A (jib)
        _click_jib_and_wait(app_page)

        # Undo A
        _undo_and_wait(app_page, row_id, "jib", orig_jib)
        expect(app_page.locator(REDO_BTN)).to_be_enabled()

        # Change B (rev) — should clear redo stack
        rev_cb = app_page.locator(
            "#matchesGrid .ag-row:first-child .ag-cell[col-id='rev'] input"
        ).first
        rev_cb.click()
        wait_for_inline_save(app_page)
        app_page.wait_for_timeout(500)

        expect(app_page.locator(REDO_BTN)).to_be_disabled()

        # Restore
        api_update_field(row_id, "jib", original.get('jib', 0))
        api_update_field(row_id, "rev", original.get('rev', 0))
        app_page.wait_for_timeout(500)


class TestUndoOperations:

    @pytest.mark.destructive
    def test_ctrl_z_undoes_single_change(self, app_page: Page):
        _show_jib_column(app_page)

        row_id = int(app_page.evaluate(
            "() => gridApi.getDisplayedRowAtIndex(0).data._row_id"
        ))
        original = api_get_record(row_id)
        orig_jib = original.get('jib', 0)

        _click_jib_and_wait(app_page)

        # Verify change happened
        changed = api_get_record(row_id)
        assert changed['jib'] != orig_jib

        # Undo and verify
        _undo_and_wait(app_page, row_id, "jib", orig_jib)
        reverted = api_get_record(row_id)
        assert reverted['jib'] == orig_jib

        # Safety restore
        api_update_field(row_id, "jib", orig_jib)
        app_page.wait_for_timeout(500)

    @pytest.mark.destructive
    def test_ctrl_z_undoes_process_change(self, app_page: Page):
        app_page.evaluate(
            "() => gridApi.setColumnsVisible(['how_to_process'], true)"
        )
        app_page.wait_for_timeout(500)

        row_id = int(app_page.evaluate(
            "() => gridApi.getDisplayedRowAtIndex(0).data._row_id"
        ))
        original = api_get_record(row_id)
        orig_process = original.get('how_to_process', '')

        # Edit via API to avoid complex dropdown interaction
        api_update_field(row_id, "how_to_process", "Manual Review - DNP")
        # Push to undo stack via JS
        app_page.evaluate("""(args) => {
            pushUndo({
                type: 'single',
                changes: [{ rowId: args.rid, field: 'how_to_process',
                             oldValue: args.orig, newValue: 'Manual Review - DNP' }]
            });
            var node = gridApi.getRowNode(String(args.rid));
            if (node) node.setDataValue('how_to_process', 'Manual Review - DNP');
        }""", {"rid": row_id, "orig": orig_process})
        app_page.wait_for_timeout(500)

        # Undo
        _undo_and_wait(app_page, row_id, "how_to_process", orig_process)

        reverted = api_get_record(row_id)
        assert reverted['how_to_process'] == orig_process

        # Safety restore
        api_update_field(row_id, "how_to_process", orig_process)
        app_page.wait_for_timeout(500)

    @pytest.mark.destructive
    def test_multi_step_undo(self, app_page: Page):
        _show_flag_columns(app_page)

        originals = {}
        for i in range(3):
            rid = int(app_page.evaluate(
                "(idx) => gridApi.getDisplayedRowAtIndex(idx).data._row_id", i
            ))
            originals[rid] = api_get_record(rid)

        rids = list(originals.keys())
        fields = ['jib', 'rev', 'vendor']

        # Make 3 changes
        for i, field in enumerate(fields):
            cb = app_page.locator(
                f"#matchesGrid .ag-row:nth-child({i + 1}) "
                f".ag-cell[col-id='{field}'] input"
            ).first
            cb.click()
            wait_for_inline_save(app_page)
            app_page.wait_for_timeout(500)

        # Undo all 3 (most recent first: vendor, rev, jib)
        for i in range(2, -1, -1):
            _undo_and_wait(app_page, rids[i], fields[i], originals[rids[i]].get(fields[i], 0))

        # Verify all reverted
        for i, (rid, field) in enumerate(zip(rids, fields)):
            reverted = api_get_record(rid)
            assert reverted[field] == originals[rid].get(field, 0)

        # Safety restore
        for rid, orig in originals.items():
            for f in fields:
                api_update_field(rid, f, orig.get(f, 0))
        app_page.wait_for_timeout(500)

    @pytest.mark.destructive
    def test_undo_after_bulk_approve(self, app_page: Page):
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
        app_page.wait_for_timeout(2000)

        # Verify approved
        for rid in row_ids:
            assert api_get_record(rid)['recommendation'] == "APPROVED"

        # Undo bulk approve
        _undo_and_wait(app_page, row_ids[0], "recommendation", originals[row_ids[0]]['recommendation'])

        # Verify reverted
        for rid in row_ids:
            reverted = api_get_record(rid)
            assert reverted['recommendation'] == originals[rid]['recommendation']

        # Safety restore
        for rid, orig in originals.items():
            api_update_field(
                rid, "recommendation", orig.get('recommendation', '')
            )
        app_page.wait_for_timeout(500)


class TestRedoOperations:

    @pytest.mark.destructive
    def test_ctrl_y_redoes_undone_change(self, app_page: Page):
        _show_jib_column(app_page)

        row_id = int(app_page.evaluate(
            "() => gridApi.getDisplayedRowAtIndex(0).data._row_id"
        ))
        original = api_get_record(row_id)
        orig_jib = original.get('jib', 0)

        _click_jib_and_wait(app_page)
        changed_jib = api_get_record(row_id)['jib']

        # Undo
        _undo_and_wait(app_page, row_id, "jib", orig_jib)
        assert api_get_record(row_id)['jib'] == orig_jib

        # Redo
        _redo_and_wait(app_page, row_id, "jib", changed_jib)
        assert api_get_record(row_id)['jib'] == changed_jib

        # Restore
        api_update_field(row_id, "jib", orig_jib)
        app_page.wait_for_timeout(500)

    @pytest.mark.destructive
    def test_undo_redo_undo_cycle(self, app_page: Page):
        _show_jib_column(app_page)

        row_id = int(app_page.evaluate(
            "() => gridApi.getDisplayedRowAtIndex(0).data._row_id"
        ))
        original = api_get_record(row_id)
        orig_jib = original.get('jib', 0)

        _click_jib_and_wait(app_page)
        changed_jib = api_get_record(row_id)['jib']

        # Undo
        _undo_and_wait(app_page, row_id, "jib", orig_jib)
        # Redo
        _redo_and_wait(app_page, row_id, "jib", changed_jib)
        # Undo again
        _undo_and_wait(app_page, row_id, "jib", orig_jib)

        final = api_get_record(row_id)
        assert final['jib'] == orig_jib

        # Safety restore
        api_update_field(row_id, "jib", orig_jib)
        app_page.wait_for_timeout(500)

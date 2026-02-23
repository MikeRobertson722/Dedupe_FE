"""Tests for row selection, cell selection, shift+click, and Ctrl+C."""
import re
import pytest
from playwright.sync_api import Page, expect
from helpers.selectors import *
from helpers.wait_helpers import wait_for_dt_reload


class TestRowCheckboxSelection:

    def test_select_single_row(self, app_page: Page):
        first_cb = app_page.locator(ROW_CHECKBOX).first
        first_cb.check()
        expect(app_page.locator(SELECTION_INFO)).to_contain_text("1 record")

    def test_selected_row_has_highlight(self, app_page: Page):
        first_cb = app_page.locator(ROW_CHECKBOX).first
        first_cb.check()
        first_row = app_page.locator(TABLE_ROWS).first
        expect(first_row).to_have_class(re.compile(r"row-selected"))

    def test_select_all_checkbox(self, app_page: Page):
        app_page.check(SELECT_ALL_CHECKBOX)
        rows = app_page.locator(TABLE_ROWS)
        total = rows.count()
        info = app_page.locator(SELECTION_INFO).text_content()
        assert str(total) in info

    def test_deselect_all(self, app_page: Page):
        app_page.check(SELECT_ALL_CHECKBOX)
        app_page.uncheck(SELECT_ALL_CHECKBOX)
        expect(app_page.locator(SELECTION_INFO)).to_contain_text("No records selected")

    def test_bulk_approve_disabled_without_selection(self, app_page: Page):
        expect(app_page.locator(BULK_APPROVE_BTN)).to_be_disabled()

    def test_bulk_approve_enabled_with_selection(self, app_page: Page):
        app_page.locator(ROW_CHECKBOX).first.check()
        expect(app_page.locator(BULK_APPROVE_BTN)).to_be_enabled()


class TestCellSelection:

    def test_single_cell_click(self, app_page: Page):
        # Click a canvas name cell (7th visible column after How to Process insertion)
        cell = app_page.locator("#matchesTable tbody tr:first-child td:nth-child(7)")
        cell.click()
        expect(cell).to_have_class(re.compile(r"cell-selected"))

    def test_click_outside_clears_selection(self, app_page: Page):
        cell = app_page.locator("#matchesTable tbody tr:first-child td:nth-child(7)")
        cell.click()
        expect(cell).to_have_class(re.compile(r"cell-selected"))
        # Click navbar to clear
        app_page.locator(NAVBAR).click()
        selected = app_page.locator(CELL_SELECTED)
        assert selected.count() == 0

    def test_shift_click_same_column_range(self, app_page: Page):
        col = 7
        row1_cell = app_page.locator(f"#matchesTable tbody tr:nth-child(1) td:nth-child({col})")
        row3_cell = app_page.locator(f"#matchesTable tbody tr:nth-child(3) td:nth-child({col})")

        row1_cell.click()
        row3_cell.click(modifiers=["Shift"])

        selected = app_page.locator(CELL_SELECTED)
        assert selected.count() >= 3


class TestCtrlCCopy:

    def test_ctrl_c_copies_cell_value(self, app_page: Page):
        app_page.context.grant_permissions(["clipboard-read", "clipboard-write"])

        cell = app_page.locator("#matchesTable tbody tr:first-child td:nth-child(7)")
        cell.click()
        expected = cell.text_content().strip()

        app_page.keyboard.press("Control+c")
        app_page.wait_for_timeout(500)

        clipboard = app_page.evaluate("() => navigator.clipboard.readText()")
        assert expected in clipboard

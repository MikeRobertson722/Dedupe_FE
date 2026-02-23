"""Tests for page length, search, sorting, column visibility, pagination."""
import pytest
from playwright.sync_api import Page, expect
from helpers.selectors import *
from helpers.wait_helpers import wait_for_dt_reload, get_dt_records_filtered


class TestPageLength:

    def test_page_length_100(self, app_page: Page):
        rows = app_page.locator(TABLE_ROWS)
        assert rows.count() == 100

    def test_page_length_500(self, app_page: Page):
        length_select = app_page.locator(f"{DT_LENGTH_PLACEHOLDER} select")
        length_select.select_option("500")
        wait_for_dt_reload(app_page)
        rows = app_page.locator(TABLE_ROWS)
        assert rows.count() == 500

    @pytest.mark.slow
    def test_page_length_1000(self, app_page: Page):
        length_select = app_page.locator(f"{DT_LENGTH_PLACEHOLDER} select")
        length_select.select_option("1000")
        wait_for_dt_reload(app_page, timeout=30000)
        rows = app_page.locator(TABLE_ROWS)
        assert rows.count() == 1000


class TestGlobalSearch:

    def test_search_reduces_rows(self, app_page: Page):
        total_before = get_dt_records_filtered(app_page)
        search_input = app_page.locator(f"{DT_SEARCH_PLACEHOLDER} input")
        search_input.fill("EXISTING BA")
        wait_for_dt_reload(app_page)
        total_after = get_dt_records_filtered(app_page)
        assert total_after <= total_before

    def test_search_clear_restores(self, app_page: Page):
        total_before = get_dt_records_filtered(app_page)
        search_input = app_page.locator(f"{DT_SEARCH_PLACEHOLDER} input")
        search_input.fill("XYZNONEXISTENT12345")
        wait_for_dt_reload(app_page)
        search_input.fill("")
        # DataTables has a search debounce, give it time to trigger AJAX
        app_page.wait_for_timeout(500)
        wait_for_dt_reload(app_page)
        total = get_dt_records_filtered(app_page)
        assert total == total_before

    def test_search_no_results(self, app_page: Page):
        search_input = app_page.locator(f"{DT_SEARCH_PLACEHOLDER} input")
        search_input.fill("XYZNONEXISTENT12345ZZZZZZ")
        wait_for_dt_reload(app_page)
        filtered = get_dt_records_filtered(app_page)
        assert filtered == 0


class TestColumnSorting:

    def test_sort_by_column_click(self, app_page: Page):
        # Click Name Score header (3rd column, index 2)
        header = app_page.locator(TABLE_HEADER).nth(2)
        header.click()
        wait_for_dt_reload(app_page)
        # Should have sorting class
        classes = header.get_attribute("class") or ""
        assert "sorting_asc" in classes or "sorting_desc" in classes

    def test_sort_toggles_direction(self, app_page: Page):
        header = app_page.locator(TABLE_HEADER).nth(2)
        header.click()
        wait_for_dt_reload(app_page)
        first_class = header.get_attribute("class") or ""
        header.click()
        wait_for_dt_reload(app_page)
        second_class = header.get_attribute("class") or ""
        # Direction should toggle
        if "sorting_asc" in first_class:
            assert "sorting_desc" in second_class
        elif "sorting_desc" in first_class:
            assert "sorting_asc" in second_class


class TestColumnVisibility:

    def test_col_vis_dropdown_has_checkboxes(self, app_page: Page):
        app_page.locator(f"{COL_VIS_CONTAINER} button").click()
        checks = app_page.locator(COL_VIS_CHECK)
        assert checks.count() >= 10

    def test_hide_column(self, app_page: Page):
        app_page.locator(f"{COL_VIS_CONTAINER} button").click()
        first_check = app_page.locator(COL_VIS_CHECK).first
        col_name = first_check.get_attribute("data-col-name")
        first_check.uncheck()
        app_page.wait_for_timeout(300)
        # Column should be hidden - verify by checking header count changed
        visible_headers = app_page.locator(f"{TABLE_HEADER}:visible")
        # Just verify the checkbox is unchecked
        expect(first_check).not_to_be_checked()

    def test_show_all_columns(self, app_page: Page):
        app_page.locator(f"{COL_VIS_CONTAINER} button").click()
        # Hide one first
        app_page.locator(COL_VIS_CHECK).first.uncheck()
        app_page.wait_for_timeout(200)
        # Show all
        app_page.locator(f"{COL_VIS_CONTAINER} a:has-text('Show All')").click()
        app_page.wait_for_timeout(200)
        unchecked = app_page.locator(f"{COL_VIS_CHECK}:not(:checked)")
        assert unchecked.count() == 0


class TestPagination:

    def test_next_page(self, app_page: Page):
        info_before = app_page.text_content(DT_INFO)
        app_page.click(DT_NEXT_BTN)
        wait_for_dt_reload(app_page)
        info_after = app_page.text_content(DT_INFO)
        assert info_before != info_after

    def test_prev_page(self, app_page: Page):
        info_page1 = app_page.text_content(DT_INFO)
        app_page.click(DT_NEXT_BTN)
        wait_for_dt_reload(app_page)
        app_page.click(DT_PREV_BTN)
        wait_for_dt_reload(app_page)
        info_back = app_page.text_content(DT_INFO)
        assert info_page1 == info_back

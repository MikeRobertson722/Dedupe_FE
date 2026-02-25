"""Tests for page size, search, sorting, column visibility, pagination."""
import pytest
from playwright.sync_api import Page, expect
from helpers.selectors import *
from helpers.wait_helpers import wait_for_grid_update, get_grid_info_counts


class TestPageSize:

    def test_default_page_size_100(self, app_page: Page):
        selected = app_page.locator(PAGE_SIZE_SELECT).input_value()
        assert selected == "100"

    def test_page_size_500(self, app_page: Page):
        app_page.select_option(PAGE_SIZE_SELECT, "500")
        wait_for_grid_update(app_page)
        # AG Grid virtualises rows so we can't count DOM rows directly;
        # verify the select value changed
        assert app_page.locator(PAGE_SIZE_SELECT).input_value() == "500"


class TestGlobalSearch:

    def test_search_reduces_rows(self, app_page: Page):
        _, total_before = get_grid_info_counts(app_page)
        app_page.fill(QUICK_FILTER_INPUT, "EXISTING BA")
        wait_for_grid_update(app_page)
        displayed, _ = get_grid_info_counts(app_page)
        assert displayed <= total_before

    def test_search_clear_restores(self, app_page: Page):
        _, total_before = get_grid_info_counts(app_page)
        app_page.fill(QUICK_FILTER_INPUT, "XYZNONEXISTENT12345")
        wait_for_grid_update(app_page)
        app_page.fill(QUICK_FILTER_INPUT, "")
        wait_for_grid_update(app_page)
        displayed, _ = get_grid_info_counts(app_page)
        assert displayed == total_before

    def test_search_no_results(self, app_page: Page):
        app_page.fill(QUICK_FILTER_INPUT, "XYZNONEXISTENT12345ZZZZZZ")
        wait_for_grid_update(app_page)
        displayed, _ = get_grid_info_counts(app_page)
        assert displayed == 0


class TestColumnSorting:

    def test_sort_by_column_click(self, app_page: Page):
        # Click the Name Score header
        header = app_page.locator(".ag-header-cell[col-id='name_score']")
        header.click()
        wait_for_grid_update(app_page)
        # AG Grid adds sort indicator classes
        sort_indicator = header.locator(".ag-sort-ascending-icon, .ag-sort-descending-icon")
        visible_indicators = 0
        for i in range(sort_indicator.count()):
            if sort_indicator.nth(i).is_visible():
                visible_indicators += 1
        assert visible_indicators >= 1

    def test_sort_toggles_direction(self, app_page: Page):
        header = app_page.locator(".ag-header-cell[col-id='name_score']")
        header.click()
        wait_for_grid_update(app_page)
        header.click()
        wait_for_grid_update(app_page)
        # Should still have a sort indicator after double click
        sort_indicator = header.locator(".ag-sort-ascending-icon, .ag-sort-descending-icon")
        visible = False
        for i in range(sort_indicator.count()):
            if sort_indicator.nth(i).is_visible():
                visible = True
                break
        assert visible


class TestColumnVisibility:

    def test_col_vis_dropdown_has_checkboxes(self, app_page: Page):
        app_page.locator(f"{COL_VIS_CONTAINER} button").click()
        checks = app_page.locator(COL_VIS_CHECK)
        assert checks.count() >= 10

    def test_hide_column(self, app_page: Page):
        app_page.locator(f"{COL_VIS_CONTAINER} button").click()
        first_check = app_page.locator(COL_VIS_CHECK).first
        first_check.uncheck()
        app_page.wait_for_timeout(300)
        expect(first_check).not_to_be_checked()

    def test_show_all_columns(self, app_page: Page):
        app_page.locator(f"{COL_VIS_CONTAINER} button").click()
        app_page.locator(COL_VIS_CHECK).first.uncheck()
        app_page.wait_for_timeout(200)
        app_page.locator(f"{COL_VIS_CONTAINER} a:has-text('Show All')").click()
        app_page.wait_for_timeout(200)
        unchecked = app_page.locator(f"{COL_VIS_CHECK}:not(:checked)")
        assert unchecked.count() == 0


class TestPagination:

    def test_pagination_present(self, app_page: Page):
        # AG Grid pagination panel should be visible
        paging = app_page.locator(".ag-paging-panel")
        expect(paging).to_be_visible()

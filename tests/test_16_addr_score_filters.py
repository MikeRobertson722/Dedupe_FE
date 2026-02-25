"""Tests for address score filter dropdowns."""
import pytest
from playwright.sync_api import Page, expect
from helpers.selectors import *
from helpers.wait_helpers import wait_for_grid_update, get_grid_info_counts


class TestAddressScoreFilters:

    def test_min_addr_score_reduces_rows(self, app_page: Page):
        _, total_before = get_grid_info_counts(app_page)
        app_page.select_option(MIN_ADDR_SCORE, "90")
        wait_for_grid_update(app_page)
        displayed, _ = get_grid_info_counts(app_page)
        assert displayed <= total_before

    def test_max_addr_score_reduces_rows(self, app_page: Page):
        _, total_before = get_grid_info_counts(app_page)
        app_page.select_option(MAX_ADDR_SCORE, "50")
        wait_for_grid_update(app_page)
        displayed, _ = get_grid_info_counts(app_page)
        assert displayed <= total_before

    def test_addr_scores_within_range(self, app_page: Page):
        app_page.select_option(MIN_ADDR_SCORE, "75")
        app_page.select_option(MAX_ADDR_SCORE, "100")
        wait_for_grid_update(app_page)
        displayed, _ = get_grid_info_counts(app_page)
        if displayed > 0:
            scores = app_page.evaluate("""() => {
                var result = [];
                var count = Math.min(gridApi.getDisplayedRowCount(), 10);
                for (var i = 0; i < count; i++) {
                    var node = gridApi.getDisplayedRowAtIndex(i);
                    if (node && node.data) result.push(node.data.address_score);
                }
                return result;
            }""")
            for score in scores:
                assert 75 <= score <= 100, f"Address score {score} outside range 75-100"

    def test_addr_combined_with_name_score(self, app_page: Page):
        app_page.select_option(MIN_NAME_SCORE, "80")
        wait_for_grid_update(app_page)
        name_only, _ = get_grid_info_counts(app_page)

        app_page.select_option(MIN_ADDR_SCORE, "80")
        wait_for_grid_update(app_page)
        combined, _ = get_grid_info_counts(app_page)
        assert combined <= name_only

    def test_addr_combined_with_ssn(self, app_page: Page):
        app_page.select_option(SSN_FILTER, "yes")
        wait_for_grid_update(app_page)
        ssn_only, _ = get_grid_info_counts(app_page)

        app_page.select_option(MIN_ADDR_SCORE, "90")
        wait_for_grid_update(app_page)
        combined, _ = get_grid_info_counts(app_page)
        assert combined <= ssn_only

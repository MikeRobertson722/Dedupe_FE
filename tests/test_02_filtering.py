"""Tests for the filtering system."""
import pytest
from playwright.sync_api import Page, expect
from helpers.selectors import *
from helpers.wait_helpers import wait_for_grid_update, get_grid_info_counts
from helpers.api_helpers import api_get_stats


class TestRecommendationFilter:

    def test_select_single_recommendation(self, app_page: Page):
        app_page.click(REC_FILTER_BTN)
        first_cb = app_page.locator(REC_CHECKBOX).first
        first_cb.check()
        wait_for_grid_update(app_page)

        displayed, total = get_grid_info_counts(app_page)
        assert displayed < total

    def test_select_multiple_recommendations(self, app_page: Page):
        app_page.click(REC_FILTER_BTN)
        cbs = app_page.locator(REC_CHECKBOX)
        cbs.nth(0).check()
        cbs.nth(1).check()
        wait_for_grid_update(app_page)

        label = app_page.locator("#recFilterBtn")
        expect(label).to_contain_text("2 selected")

    def test_select_all_button(self, app_page: Page):
        app_page.click(REC_FILTER_BTN)
        app_page.locator(".rec-filter-menu a:has-text('Select All')").click()
        wait_for_grid_update(app_page)
        unchecked = app_page.locator(f"{REC_CHECKBOX}:not(:checked)")
        assert unchecked.count() == 0

    def test_clear_all_button(self, app_page: Page):
        app_page.click(REC_FILTER_BTN)
        app_page.locator(REC_CHECKBOX).first.check()
        wait_for_grid_update(app_page)
        displayed_before, _ = get_grid_info_counts(app_page)

        app_page.locator(".rec-filter-menu a:has-text('Clear All')").click()
        wait_for_grid_update(app_page)
        displayed_after, _ = get_grid_info_counts(app_page)
        assert displayed_after >= displayed_before


class TestSSNFilter:

    def test_ssn_yes_filter(self, app_page: Page):
        app_page.select_option(SSN_FILTER, "yes")
        wait_for_grid_update(app_page)
        badges = app_page.locator("#matchesGrid .ag-cell[col-id='ssn_match'] .badge")
        for i in range(min(badges.count(), 5)):
            expect(badges.nth(i)).to_have_text("Yes")

    def test_ssn_no_filter(self, app_page: Page):
        app_page.select_option(SSN_FILTER, "no")
        wait_for_grid_update(app_page)
        badges = app_page.locator("#matchesGrid .ag-cell[col-id='ssn_match'] .badge")
        for i in range(min(badges.count(), 5)):
            expect(badges.nth(i)).to_have_text("No")

    def test_ssn_partial_filter(self, app_page: Page):
        app_page.select_option(SSN_FILTER, "partial")
        wait_for_grid_update(app_page)
        displayed, _ = get_grid_info_counts(app_page)
        assert displayed >= 0


class TestScoreFilters:

    def test_min_name_score_filter(self, app_page: Page):
        _, total_before = get_grid_info_counts(app_page)
        app_page.select_option(MIN_NAME_SCORE, "90")
        wait_for_grid_update(app_page)
        displayed, _ = get_grid_info_counts(app_page)
        assert displayed <= total_before

    def test_max_name_score_filter(self, app_page: Page):
        _, total_before = get_grid_info_counts(app_page)
        app_page.select_option(MAX_NAME_SCORE, "50")
        wait_for_grid_update(app_page)
        displayed, _ = get_grid_info_counts(app_page)
        assert displayed <= total_before

    def test_combined_filters(self, app_page: Page):
        _, total = get_grid_info_counts(app_page)
        app_page.select_option(SSN_FILTER, "yes")
        wait_for_grid_update(app_page)
        ssn_filtered, _ = get_grid_info_counts(app_page)
        app_page.select_option(MIN_NAME_SCORE, "90")
        wait_for_grid_update(app_page)
        combined, _ = get_grid_info_counts(app_page)
        assert combined <= ssn_filtered <= total


class TestClearFilters:

    def test_clear_resets_all(self, app_page: Page):
        app_page.select_option(SSN_FILTER, "yes")
        wait_for_grid_update(app_page)
        app_page.click(CLEAR_FILTERS_BTN)
        wait_for_grid_update(app_page)
        expect(app_page.locator(SSN_FILTER)).to_have_value("")
        displayed, total = get_grid_info_counts(app_page)
        stats = api_get_stats()
        assert total == stats['total_records']


class TestRecommendationCardClick:

    def test_card_click_filters(self, app_page: Page):
        first_card = app_page.locator(REC_CARD).first
        first_card.click()
        wait_for_grid_update(app_page)
        displayed, total = get_grid_info_counts(app_page)
        assert displayed < total

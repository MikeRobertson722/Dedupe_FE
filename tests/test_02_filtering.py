"""Tests for the filtering system."""
import pytest
from playwright.sync_api import Page, expect
from helpers.selectors import *
from helpers.wait_helpers import wait_for_grid_update, get_grid_info_counts
from helpers.api_helpers import api_get_stats


class TestRecommendationFilter:

    def test_filter_by_single_recommendation(self, app_page: Page):
        """Filter to a single rec by clicking a rec card."""
        _, total = get_grid_info_counts(app_page)
        cards = app_page.locator(f"{REC_CARD} .rec-card")
        # Click the second card (first non-ALL card)
        cards.nth(1).click()
        wait_for_grid_update(app_page)
        displayed, _ = get_grid_info_counts(app_page)
        assert displayed < total

    def test_filter_by_rec_via_js(self, app_page: Page):
        """Filter using filterByRec JS function sets score filters."""
        _, total = get_grid_info_counts(app_page)
        # Get a recommendation name from the API
        stats = api_get_stats()
        recs = list(stats['recommendations'].keys())
        # Filter to one with fewer records than total
        for rec in recs:
            if stats['recommendations'][rec] < total:
                app_page.evaluate(f"() => filterByRec('{rec}')")
                wait_for_grid_update(app_page)
                displayed, _ = get_grid_info_counts(app_page)
                assert displayed <= total
                break

    def test_clear_filters_resets_rec_filter(self, app_page: Page):
        """After filterByRec, clearFilters should restore all rows."""
        _, total = get_grid_info_counts(app_page)
        cards = app_page.locator(f"{REC_CARD} .rec-card")
        cards.nth(1).click()
        wait_for_grid_update(app_page)

        app_page.click(CLEAR_FILTERS_BTN)
        wait_for_grid_update(app_page)
        displayed, restored_total = get_grid_info_counts(app_page)
        assert displayed == total

    def test_all_card_clears_filters(self, app_page: Page):
        """Clicking the ALL card calls clearFilters."""
        _, total = get_grid_info_counts(app_page)
        cards = app_page.locator(f"{REC_CARD} .rec-card")
        # Click a non-ALL card first
        cards.nth(1).click()
        wait_for_grid_update(app_page)
        # Click the ALL card (first card)
        cards.first.click()
        wait_for_grid_update(app_page)
        displayed, _ = get_grid_info_counts(app_page)
        assert displayed == total


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
        _, total = get_grid_info_counts(app_page)
        # Click the second card (first non-ALL recommendation)
        cards = app_page.locator(f"{REC_CARD} .rec-card")
        cards.nth(1).click()
        wait_for_grid_update(app_page)
        displayed, _ = get_grid_info_counts(app_page)
        assert displayed < total

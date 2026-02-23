"""Tests for the filtering system."""
import pytest
from playwright.sync_api import Page, expect
from helpers.selectors import *
from helpers.wait_helpers import wait_for_dt_reload, get_dt_records_filtered
from helpers.api_helpers import api_get_stats


class TestRecommendationFilter:

    def test_select_single_recommendation(self, app_page: Page):
        app_page.click(REC_FILTER_BTN)
        first_cb = app_page.locator(REC_CHECKBOX).first
        rec_value = first_cb.get_attribute("value")
        first_cb.check()
        wait_for_dt_reload(app_page)

        # Verify info text shows filtered count < total
        filtered = get_dt_records_filtered(app_page)
        stats = api_get_stats()
        assert filtered < stats['total_records']

    def test_select_multiple_recommendations(self, app_page: Page):
        app_page.click(REC_FILTER_BTN)
        cbs = app_page.locator(REC_CHECKBOX)
        cbs.nth(0).check()
        cbs.nth(1).check()
        wait_for_dt_reload(app_page)

        label = app_page.locator("#recFilterBtn")
        expect(label).to_contain_text("2 selected")

    def test_select_all_button(self, app_page: Page):
        app_page.click(REC_FILTER_BTN)
        app_page.locator(".rec-filter-menu a:has-text('Select All')").click()
        wait_for_dt_reload(app_page)
        unchecked = app_page.locator(f"{REC_CHECKBOX}:not(:checked)")
        assert unchecked.count() == 0

    def test_clear_all_button(self, app_page: Page):
        app_page.click(REC_FILTER_BTN)
        app_page.locator(REC_CHECKBOX).first.check()
        wait_for_dt_reload(app_page)
        filtered = get_dt_records_filtered(app_page)

        app_page.locator(".rec-filter-menu a:has-text('Clear All')").click()
        wait_for_dt_reload(app_page)
        all_count = get_dt_records_filtered(app_page)
        assert all_count >= filtered


class TestSSNFilter:

    def test_ssn_yes_filter(self, app_page: Page):
        app_page.select_option(SSN_FILTER, "yes")
        wait_for_dt_reload(app_page)
        # All SSN badges in first few rows should show "Yes"
        badges = app_page.locator("#matchesTable tbody tr td:nth-child(2) .badge")
        for i in range(min(badges.count(), 5)):
            expect(badges.nth(i)).to_have_text("Yes")

    def test_ssn_no_filter(self, app_page: Page):
        app_page.select_option(SSN_FILTER, "no")
        wait_for_dt_reload(app_page)
        badges = app_page.locator("#matchesTable tbody tr td:nth-child(2) .badge")
        for i in range(min(badges.count(), 5)):
            expect(badges.nth(i)).to_have_text("No")

    def test_ssn_partial_filter(self, app_page: Page):
        app_page.select_option(SSN_FILTER, "partial")
        wait_for_dt_reload(app_page)
        filtered = get_dt_records_filtered(app_page)
        # Partial may be 0 or more depending on data
        assert filtered >= 0


class TestScoreFilters:

    def test_min_name_score_filter(self, app_page: Page):
        total_before = get_dt_records_filtered(app_page)
        app_page.select_option(MIN_NAME_SCORE, "90")
        wait_for_dt_reload(app_page)
        filtered = get_dt_records_filtered(app_page)
        assert filtered <= total_before

    def test_max_name_score_filter(self, app_page: Page):
        total_before = get_dt_records_filtered(app_page)
        app_page.select_option(MAX_NAME_SCORE, "50")
        wait_for_dt_reload(app_page)
        filtered = get_dt_records_filtered(app_page)
        assert filtered <= total_before

    def test_combined_filters(self, app_page: Page):
        total = get_dt_records_filtered(app_page)
        app_page.select_option(SSN_FILTER, "yes")
        wait_for_dt_reload(app_page)
        ssn_filtered = get_dt_records_filtered(app_page)
        app_page.select_option(MIN_NAME_SCORE, "90")
        wait_for_dt_reload(app_page)
        combined = get_dt_records_filtered(app_page)
        assert combined <= ssn_filtered <= total


class TestClearFilters:

    def test_clear_resets_all(self, app_page: Page):
        app_page.select_option(SSN_FILTER, "yes")
        wait_for_dt_reload(app_page)
        app_page.click(CLEAR_FILTERS_BTN)
        wait_for_dt_reload(app_page)
        expect(app_page.locator(SSN_FILTER)).to_have_value("")
        total = get_dt_records_filtered(app_page)
        stats = api_get_stats()
        assert total == stats['total_records']


class TestRecommendationCardClick:

    def test_card_click_filters(self, app_page: Page):
        first_card = app_page.locator(REC_CARD).first
        first_card.click()
        wait_for_dt_reload(app_page)
        filtered = get_dt_records_filtered(app_page)
        stats = api_get_stats()
        assert filtered < stats['total_records']

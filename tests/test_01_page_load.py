"""Tests for initial page load and AG Grid initialization."""
import re
import pytest
from playwright.sync_api import Page, expect
from helpers.selectors import *
from helpers.wait_helpers import get_grid_info_counts
from helpers.api_helpers import api_get_stats


class TestPageLoad:

    @pytest.mark.smoke
    def test_page_returns_200(self, page: Page, app_server):
        response = page.goto("http://127.0.0.1:5000")
        assert response.status == 200

    @pytest.mark.smoke
    def test_page_title(self, app_page: Page):
        expect(app_page).to_have_title("BA/Address Import - (Canvas - Enertia)")

    def test_navbar_present(self, app_page: Page):
        expect(app_page.locator(NAVBAR)).to_be_visible()
        expect(app_page.locator(NAVBAR)).to_contain_text("BA/Address Import")

    @pytest.mark.smoke
    def test_grid_renders_with_data(self, app_page: Page):
        rows = app_page.locator(GRID_ROW)
        expect(rows.first).to_be_visible()
        assert rows.count() > 0

    def test_recommendation_cards_appear(self, app_page: Page):
        cards = app_page.locator(REC_CARD)
        assert cards.count() >= 2

    def test_recommendation_card_counts_match_api(self, app_page: Page):
        stats = api_get_stats()
        total_from_cards = 0
        cards = app_page.locator(REC_CARD)
        for i in range(cards.count()):
            card_text = cards.nth(i).text_content()
            nums = re.findall(r'[\d,]+', card_text)
            if nums:
                total_from_cards += int(nums[0].replace(',', ''))
        assert total_from_cards == stats['total_records']

    def test_ssn_filter_has_options(self, app_page: Page):
        options = app_page.locator(f"{SSN_FILTER} option")
        assert options.count() == 4  # All, Yes, Partial, No

    def test_rec_filter_dropdown_built(self, app_page: Page):
        app_page.click(REC_FILTER_BTN)
        checkboxes = app_page.locator(REC_CHECKBOX)
        assert checkboxes.count() >= 2

    def test_datasource_selector_populated(self, app_page: Page):
        options = app_page.locator(f"{DATASOURCE_SELECTOR} option")
        assert options.count() >= 2

    def test_default_page_size_is_100(self, app_page: Page):
        selected = app_page.locator(PAGE_SIZE_SELECT).input_value()
        assert selected == "100"

    def test_grid_info_shows_record_count(self, app_page: Page):
        displayed, total = get_grid_info_counts(app_page)
        assert total > 0

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
        expect(app_page).to_have_title("AssociateIQ -  Source (Enertia) -> Target: DEC (Enertia)")

    def test_navbar_present(self, app_page: Page):
        expect(app_page.locator(NAVBAR)).to_be_visible()
        expect(app_page.locator(NAVBAR)).to_contain_text("AssociateIQ")

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
        cards = app_page.locator(f"{REC_CARD} .rec-card")
        for i in range(cards.count()):
            card_text = cards.nth(i).text_content()
            # Card text is like "REC_NAME - 1,234 (5.6%)" or "ALL - 31,695"
            # Extract the count after the dash, before the optional pct
            m = re.search(r'-\s*([\d,]+)', card_text)
            if m:
                total_from_cards += int(m.group(1).replace(',', ''))
        # Total should be the ALL card count + each rec count = 2x total,
        # or we can just check per-rec cards sum to total
        # The ALL card also has total_records, so sum of all cards = 2 * total
        # Instead, check that the per-rec cards (excluding ALL) sum to total
        per_rec_total = 0
        all_card_count = 0
        for i in range(cards.count()):
            card_text = cards.nth(i).text_content()
            m = re.search(r'-\s*([\d,]+)', card_text)
            if m:
                count = int(m.group(1).replace(',', ''))
                if 'ALL' in card_text:
                    all_card_count = count
                else:
                    per_rec_total += count
        assert all_card_count == stats['total_records']
        assert per_rec_total == stats['total_records']

    def test_ssn_filter_has_options(self, app_page: Page):
        options = app_page.locator(f"{SSN_FILTER} option")
        assert options.count() == 3  # All, Yes, No (Partial removed)

    def test_rec_filter_uses_card_click(self, app_page: Page):
        """Rec filtering is done via clickable rec cards, not a dropdown."""
        cards = app_page.locator(f"{REC_CARD} .rec-card")
        assert cards.count() >= 2
        # Each non-ALL card has an onclick filterByRec
        second_card = cards.nth(1)
        onclick = second_card.get_attribute("onclick") or ""
        assert "filterByRec" in onclick

    def test_snowflake_label_present(self, app_page: Page):
        """Snowflake is the data source, shown as a label in the navbar."""
        expect(app_page.locator("nav.navbar")).to_contain_text("Snowflake")

    def test_grid_info_shows_record_count(self, app_page: Page):
        displayed, total = get_grid_info_counts(app_page)
        assert total > 0

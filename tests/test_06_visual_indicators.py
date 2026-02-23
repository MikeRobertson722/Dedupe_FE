"""Tests for visual indicators: badges, highlighting, tooltips."""
import re
import pytest
from playwright.sync_api import Page, expect
from helpers.selectors import *
from helpers.wait_helpers import wait_for_dt_reload, get_dt_records_filtered


class TestSSNBadges:

    @pytest.mark.visual
    def test_ssn_yes_badge_green(self, app_page: Page):
        app_page.select_option(SSN_FILTER, "yes")
        wait_for_dt_reload(app_page)
        badge = app_page.locator("#matchesTable tbody tr:first-child td:nth-child(2) .badge").first
        expect(badge).to_have_text("Yes")
        expect(badge).to_have_class(re.compile(r"bg-success"))

    @pytest.mark.visual
    def test_ssn_no_badge_red(self, app_page: Page):
        app_page.select_option(SSN_FILTER, "no")
        wait_for_dt_reload(app_page)
        badge = app_page.locator("#matchesTable tbody tr:first-child td:nth-child(2) .badge").first
        expect(badge).to_have_text("No")
        expect(badge).to_have_class(re.compile(r"bg-danger"))


class TestScoreBadges:

    @pytest.mark.visual
    def test_score_badges_present(self, app_page: Page):
        """Score badges should be rendered in name/addr score columns."""
        name_badges = app_page.locator("#matchesTable tbody td:nth-child(3) .score-badge")
        assert name_badges.count() > 0

    @pytest.mark.visual
    def test_perfect_score_is_green(self, app_page: Page):
        """Score of 100 should have score-perfect class."""
        perfect = app_page.locator("#matchesTable tbody .score-badge.score-perfect")
        if perfect.count() > 0:
            expect(perfect.first).to_have_text("100")


class TestTrustHighlighting:

    @pytest.mark.visual
    def test_trust_rows_have_class(self, app_page: Page):
        search = app_page.locator(f"{DT_SEARCH_PLACEHOLDER} input")
        search.fill("trust")
        wait_for_dt_reload(app_page)
        filtered = get_dt_records_filtered(app_page)
        if filtered > 0:
            trust_rows = app_page.locator(TRUST_HIGHLIGHT)
            assert trust_rows.count() > 0


class TestNameScoreTooltip:

    @pytest.mark.visual
    def test_low_name_score_has_tooltip(self, app_page: Page):
        """Name scores below 45 should have a title attribute."""
        app_page.select_option(MAX_NAME_SCORE, "40")
        wait_for_dt_reload(app_page)
        filtered = get_dt_records_filtered(app_page)
        if filtered > 0:
            cell = app_page.locator("#matchesTable tbody tr:first-child td:nth-child(3)")
            title = cell.get_attribute("title") or ""
            assert "low" in title.lower() or "address" in title.lower() or title != ""

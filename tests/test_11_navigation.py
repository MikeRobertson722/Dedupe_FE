"""Tests for help modal, dev notes button, and refresh."""
import pytest
from playwright.sync_api import Page, expect
from helpers.selectors import *
from helpers.wait_helpers import wait_for_modal_visible, wait_for_toast, wait_for_grid_update


class TestHelpModal:

    def test_help_opens(self, app_page: Page):
        app_page.click(HELP_BTN)
        wait_for_modal_visible(app_page, HELP_MODAL)
        expect(app_page.locator(HELP_MODAL)).to_be_visible()

    def test_help_has_accordion_sections(self, app_page: Page):
        app_page.click(HELP_BTN)
        wait_for_modal_visible(app_page, HELP_MODAL)
        sections = app_page.locator(f"{HELP_ACCORDION} .accordion-item")
        assert sections.count() == 8

    def test_help_closes(self, app_page: Page):
        app_page.click(HELP_BTN)
        wait_for_modal_visible(app_page, HELP_MODAL)
        app_page.locator("#helpModal .btn-secondary").click()
        app_page.wait_for_timeout(400)
        expect(app_page.locator(HELP_MODAL)).to_be_hidden()


class TestDevNotes:

    def test_dev_notes_sends_api_request(self, app_page: Page):
        with app_page.expect_request("**/api/dev_notes") as req_info:
            app_page.click(DEV_NOTES_BTN)
        request = req_info.value
        assert "/api/dev_notes" in request.url


class TestRefresh:

    def test_refresh_triggers_reload(self, app_page: Page):
        with app_page.expect_request("**/api/reload") as req_info:
            app_page.click(REFRESH_BTN)
        request = req_info.value
        assert request.method == "POST"

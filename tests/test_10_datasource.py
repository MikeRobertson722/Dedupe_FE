"""Tests for data source display."""
import pytest
from playwright.sync_api import Page, expect
from helpers.selectors import *
from helpers.api_helpers import api_get_datasources


class TestDataSourceDisplay:

    def test_snowflake_label_in_navbar(self, app_page: Page):
        """Datasource is shown as a static Snowflake label in the navbar."""
        expect(app_page.locator("nav.navbar")).to_contain_text("Snowflake")

    def test_api_returns_active_source(self, app_page: Page):
        """The datasources API reports an active source."""
        ds = api_get_datasources()
        assert 'active' in ds
        assert ds['active'] != ""

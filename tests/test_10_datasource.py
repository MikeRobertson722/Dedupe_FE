"""Tests for data source selector."""
import pytest
from playwright.sync_api import Page, expect
from helpers.selectors import *
from helpers.api_helpers import api_get_datasources


class TestDataSourceSelector:

    def test_dropdown_populated(self, app_page: Page):
        ds = api_get_datasources()
        options = app_page.locator(f"{DATASOURCE_SELECTOR} option")
        # Should have at least as many options as configured sources
        assert options.count() >= len(ds['datasources'])

    def test_active_source_selected(self, app_page: Page):
        ds = api_get_datasources()
        active = ds['active']
        selected = app_page.locator(DATASOURCE_SELECTOR).input_value()
        assert selected == active

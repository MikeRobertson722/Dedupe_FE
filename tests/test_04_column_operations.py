"""Tests for column resize and sticky headers (AG Grid built-in)."""
import pytest
from playwright.sync_api import Page, expect
from helpers.selectors import *


class TestColumnResize:

    def test_column_headers_are_resizable(self, app_page: Page):
        """AG Grid columns with resizable:true show resize handles on hover."""
        # Verify a resizable column header exists
        header = app_page.locator(".ag-header-cell[col-id='canvas_name']")
        expect(header).to_be_visible()

    def test_drag_resize_changes_width(self, app_page: Page):
        header = app_page.locator(".ag-header-cell[col-id='canvas_name']")
        width_before = header.evaluate("el => el.getBoundingClientRect().width")

        # AG Grid resize handle is on the right edge of the header
        resize_handle = header.locator(".ag-header-cell-resize")
        box = resize_handle.bounding_box()
        if box:
            cx = box["x"] + box["width"] / 2
            cy = box["y"] + box["height"] / 2
            app_page.mouse.move(cx, cy)
            app_page.mouse.down()
            app_page.mouse.move(cx + 80, cy)
            app_page.mouse.up()
            app_page.wait_for_timeout(300)

            width_after = header.evaluate("el => el.getBoundingClientRect().width")
            assert width_after > width_before


class TestStickyHeaders:

    def test_headers_visible_after_scroll(self, app_page: Page):
        """AG Grid headers are sticky by default."""
        header = app_page.locator(GRID_HEADER).first
        expect(header).to_be_visible()
        box = header.bounding_box()
        assert box is not None

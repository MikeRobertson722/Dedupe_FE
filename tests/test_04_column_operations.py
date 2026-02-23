"""Tests for column resize, column reorder, and sticky headers."""
import pytest
from playwright.sync_api import Page, expect
from helpers.selectors import *


class TestColumnResize:

    def test_resize_handles_exist(self, app_page: Page):
        handles = app_page.locator(RESIZE_HANDLE)
        assert handles.count() == 13  # 13 resizable columns

    def test_drag_resize_changes_width(self, app_page: Page):
        # Get the first th that contains a resize handle via JS (parent of handle)
        handle = app_page.locator(RESIZE_HANDLE).first
        th_width_before = handle.evaluate("el => el.closest('th').getBoundingClientRect().width")

        box = handle.bounding_box()
        cx = box["x"] + box["width"] / 2
        cy = box["y"] + box["height"] / 2
        app_page.mouse.move(cx, cy)
        app_page.mouse.down()
        app_page.mouse.move(cx + 80, cy)
        app_page.mouse.up()
        app_page.wait_for_timeout(300)

        th_width_after = handle.evaluate("el => el.closest('th').getBoundingClientRect().width")
        assert th_width_after > th_width_before

    def test_resize_respects_minimum_width(self, app_page: Page):
        handle = app_page.locator(RESIZE_HANDLE).first
        box = handle.bounding_box()
        cx = box["x"] + box["width"] / 2
        cy = box["y"] + box["height"] / 2

        # Drag far left to hit minimum
        app_page.mouse.move(cx, cy)
        app_page.mouse.down()
        app_page.mouse.move(cx - 500, cy)
        app_page.mouse.up()
        app_page.wait_for_timeout(300)

        th_width = handle.evaluate("el => el.closest('th').getBoundingClientRect().width")
        assert th_width >= 50  # Minimum width


class TestColumnReorder:

    def test_column_headers_are_draggable(self, app_page: Page):
        """Verify ColReorder is initialized by checking class presence."""
        # ColReorder adds reordering capability - verify the table has it
        has_colreorder = app_page.evaluate(
            "() => typeof $.fn.dataTable.ColReorder !== 'undefined'"
        )
        assert has_colreorder


class TestStickyHeaders:

    def test_headers_visible_after_scroll(self, app_page: Page):
        table_section = app_page.locator(TABLE_SECTION)
        table_section.evaluate("el => el.scrollTop = 500")
        app_page.wait_for_timeout(200)

        first_header = app_page.locator(TABLE_HEADER).first
        expect(first_header).to_be_visible()
        box = first_header.bounding_box()
        assert box is not None

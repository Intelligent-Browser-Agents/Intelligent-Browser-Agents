"""
Live browser smoke tests for the action-execution layer.

These drive real Chromium against live public sites, so they are marked
``browser`` and deselected by default (see pyproject.toml). Run them explicitly
with:

    pytest -m browser backend/tests/test_action_system.py

They are intentionally coarse end-to-end checks. Phase 8 of
docs/IMPROVEMENT_PLAN.md replaces the live-site targets with local HTML fixtures
so these no longer depend on network conditions or third-party anti-bot behaviour.

The ``page`` fixture is provided by backend/tests/conftest.py.
"""

import asyncio
import json
import time

import pytest
from playwright.async_api import Page

from execution import Action, ActionArgs, dispatch_action
from dom_extraction import dom_extractor

pytestmark = pytest.mark.browser


async def test_dom_extraction_aria_format(page: Page):
    """DOM extraction returns interactive elements in role/name (ARIA) form."""
    await page.goto("https://www.google.com")
    await page.wait_for_load_state("domcontentloaded")

    result = await dom_extractor.main(page)
    assert isinstance(result, tuple), f"expected (json, screenshot, page) tuple, got {type(result)}"

    dom_data = json.loads(result[0])
    assert dom_data.get("status") == "success"

    interactive_data = json.loads(dom_extractor.retrieve_interactive_elements(result[0]))
    assert interactive_data.get("status") == "success"

    elements = interactive_data.get("interactive_elements", [])
    assert elements, "no interactive elements extracted"
    for elem in elements[:5]:
        assert "role" in elem and "name" in elem, f"element missing role/name: {elem}"


async def test_action_navigate(page: Page):
    result = await dispatch_action(
        page, Action(action="navigate", args=ActionArgs(url="https://www.example.com"))
    )
    assert result.status == "success", f"{result.error_type}: {result.message}"
    assert "example.com" in page.url


async def test_action_click(page: Page):
    await page.goto("https://www.google.com")
    await page.wait_for_load_state("domcontentloaded")

    result = await dispatch_action(
        page, Action(action="click", args=ActionArgs(role="combobox", name="Search"))
    )
    if result.status != "success":
        # The search field's role varies; textbox is the common alternate.
        result = await dispatch_action(
            page, Action(action="click", args=ActionArgs(role="textbox", name="Search"))
        )
    assert result.status == "success", f"{result.error_type}: {result.message}"


async def test_action_type(page: Page):
    await page.goto("https://www.google.com")
    await page.wait_for_load_state("domcontentloaded")
    await page.click('textarea[name="q"]')
    await asyncio.sleep(0.5)

    result = await dispatch_action(
        page, Action(action="type", args=ActionArgs(text="Hello World Test"))
    )
    assert result.status == "success", f"{result.error_type}: {result.message}"
    assert "Hello World Test" in await page.input_value('textarea[name="q"]')


async def test_action_search(page: Page):
    await page.goto("https://www.google.com")
    await page.wait_for_load_state("domcontentloaded")

    result = await dispatch_action(
        page, Action(action="search", args=ActionArgs(text="Playwright testing"))
    )
    assert result.status == "success", f"{result.error_type}: {result.message}"
    await asyncio.sleep(2)
    assert "search" in page.url or "Playwright" in await page.content()


async def test_action_scroll(page: Page):
    await page.goto("https://en.wikipedia.org/wiki/Web_browser")
    await page.wait_for_load_state("domcontentloaded")
    initial_y = await page.evaluate("window.scrollY")

    result = await dispatch_action(
        page, Action(action="scroll", args=ActionArgs(direction="down"))
    )
    assert result.status == "success", f"{result.error_type}: {result.message}"
    await asyncio.sleep(0.5)
    assert await page.evaluate("window.scrollY") > initial_y


async def test_action_press_key(page: Page):
    await page.goto("https://www.google.com")
    await page.wait_for_load_state("domcontentloaded")
    await page.click('textarea[name="q"]')
    await page.type('textarea[name="q"]', "Test Query")
    await asyncio.sleep(0.5)

    result = await dispatch_action(
        page, Action(action="press_key", args=ActionArgs(key="Enter"))
    )
    assert result.status == "success", f"{result.error_type}: {result.message}"
    await asyncio.sleep(2)
    assert "search" in page.url


async def test_action_wait(page: Page):
    start_time = time.monotonic()
    result = await dispatch_action(
        page, Action(action="wait", args=ActionArgs(seconds=2.0))
    )
    elapsed = time.monotonic() - start_time
    assert result.status == "success", f"{result.error_type}: {result.message}"
    assert 1.5 <= elapsed <= 3.0, f"wait was {elapsed:.2f}s, expected ~2.0s"

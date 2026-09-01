"""
Browser smoke tests for the action-execution layer.

These drive real Chromium against the local fixture site (see the `site` fixture
in conftest.py), so they need a browser but no network. Run them with:

    pytest -m browser backend/tests/test_action_system.py

They used to point at google.com, example.com, and wikipedia.org. Google serves
an anti-bot interstitial to automated Chromium, so the assertions were made
against a page that changed without notice, and none of these could run in CI.
Phase 8 of docs/IMPROVEMENT_PLAN.md replaced the targets with fixtures.

They remain intentionally coarse: this file answers "does dispatch reach the
handler and come back with a sane result", not "is the handler correct". The
per-primitive behaviour lives in test_action_layer.py and test_fixture_site.py.

The ``page`` fixture is provided by backend/tests/conftest.py.
"""

import time

import pytest
from playwright.async_api import Page

from execution import Action, ActionArgs, dispatch_action
from dom_extraction.snapshot import capture_page_snapshot

pytestmark = pytest.mark.browser


async def test_snapshot_extracts_elements_from_a_real_page(page: Page, site):
    """The unified snapshot returns addressable role/name elements."""
    await page.goto(f"{site}/listings.html")
    await page.wait_for_load_state("domcontentloaded")

    snapshot = await capture_page_snapshot(page)
    assert snapshot.elements, "no interactive elements extracted"
    for element in snapshot.elements[:5]:
        assert element.role and element.ref
    assert any(e.role in {"button", "combobox", "textbox", "link"} for e in snapshot.elements)


async def test_action_navigate(page: Page, site):
    result = await dispatch_action(
        page, Action(action="navigate", args=ActionArgs(url=f"{site}/listings.html"))
    )
    assert result.status == "success", f"{result.error_type}: {result.message}"
    assert "listings.html" in page.url


async def test_action_click(page: Page, site):
    await page.goto(f"{site}/listings.html")
    await page.wait_for_load_state("domcontentloaded")

    result = await dispatch_action(
        page, Action(action="click", args=ActionArgs(role="searchbox", name="Search roles"))
    )
    assert result.status == "success", f"{result.error_type}: {result.message}"


async def test_action_type(page: Page, site):
    await page.goto(f"{site}/listings.html")
    await page.wait_for_load_state("domcontentloaded")
    await page.click("#q")

    result = await dispatch_action(
        page, Action(action="type", args=ActionArgs(text="Platform Engineer"))
    )
    assert result.status == "success", f"{result.error_type}: {result.message}"
    assert "Platform Engineer" in await page.input_value("#q")


async def test_action_search(page: Page, site):
    await page.goto(f"{site}/listings.html")
    await page.wait_for_load_state("domcontentloaded")

    result = await dispatch_action(
        page, Action(action="search", args=ActionArgs(text="platform"))
    )
    assert result.status == "success", f"{result.error_type}: {result.message}"
    # The query reaching the URL is the observable proof the submit happened.
    await page.wait_for_url("**/listings.html?q=platform")


async def test_action_scroll(page: Page, site):
    await page.goto(f"{site}/tall_page.html")
    await page.wait_for_load_state("domcontentloaded")
    initial_y = await page.evaluate("window.scrollY")

    result = await dispatch_action(
        page, Action(action="scroll", args=ActionArgs(direction="down"))
    )
    assert result.status == "success", f"{result.error_type}: {result.message}"
    assert await page.evaluate("window.scrollY") > initial_y


async def test_action_press_key(page: Page, site):
    await page.goto(f"{site}/listings.html")
    await page.wait_for_load_state("domcontentloaded")
    await page.click("#q")
    await page.type("#q", "security")

    result = await dispatch_action(
        page, Action(action="press_key", args=ActionArgs(key="Enter"))
    )
    assert result.status == "success", f"{result.error_type}: {result.message}"
    await page.wait_for_url("**/listings.html?q=security")


async def test_action_wait(page: Page):
    start_time = time.monotonic()
    result = await dispatch_action(
        page, Action(action="wait", args=ActionArgs(seconds=2.0))
    )
    elapsed = time.monotonic() - start_time
    assert result.status == "success", f"{result.error_type}: {result.message}"
    assert 1.5 <= elapsed <= 3.0, f"wait was {elapsed:.2f}s, expected ~2.0s"

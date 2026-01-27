"""
Pytest configuration and fixtures for execution tests.
"""

import pytest_asyncio
from playwright.async_api import async_playwright


@pytest_asyncio.fixture(scope="function")
async def page():
    """
    Provide a Playwright page for testing.

    Creates a new browser instance for each test (slower but most reliable).
    Typical run time: ~2.5 seconds per test, ~42 seconds for 17 tests total.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        yield page

        await page.close()
        await context.close()
        await browser.close()

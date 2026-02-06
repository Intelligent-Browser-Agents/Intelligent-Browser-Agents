"""
Systematic Test Suite for Action Execution System

Tests:
1. DOM Extraction - ARIA format output
2. All 7 action handlers (navigate, click, type, search, scroll, press_key, wait)
3. Integration with real browser

Run: python -m src.test_action_system
"""

import asyncio
import json
from playwright.async_api import async_playwright, Page
from src.execution import Action, ActionArgs, dispatch_action
from src.dom_extraction import dom_extractor


class TestResults:
    """Track test results."""
    def __init__(self):
        self.passed = []
        self.failed = []
        self.total = 0

    def add_pass(self, test_name: str, message: str = ""):
        self.total += 1
        self.passed.append((test_name, message))
        print(f"✓ PASS: {test_name}")
        if message:
            print(f"  → {message}")

    def add_fail(self, test_name: str, error: str):
        self.total += 1
        self.failed.append((test_name, error))
        print(f"✗ FAIL: {test_name}")
        print(f"  → {error}")

    def print_summary(self):
        print("\n" + "=" * 80)
        print("TEST SUMMARY")
        print("=" * 80)
        print(f"Total Tests: {self.total}")
        print(f"Passed: {len(self.passed)} ({len(self.passed)/self.total*100:.1f}%)")
        print(f"Failed: {len(self.failed)} ({len(self.failed)/self.total*100:.1f}%)")

        if self.failed:
            print("\n" + "-" * 80)
            print("FAILED TESTS:")
            print("-" * 80)
            for test_name, error in self.failed:
                print(f"✗ {test_name}")
                print(f"  {error}")

        print("=" * 80)


results = TestResults()


async def test_dom_extraction_aria_format(page: Page):
    """Test that DOM extraction returns ARIA-formatted data."""
    print("\n" + "=" * 80)
    print("TEST 1: DOM Extraction - ARIA Format")
    print("=" * 80)

    try:
        # Navigate to Google for testing
        await page.goto("https://www.google.com")
        await page.wait_for_load_state("networkidle")

        # Get DOM extraction
        result = await dom_extractor.main(page)

        # Parse result (returns tuple: (json_data, screenshot, page))
        if isinstance(result, tuple):
            dom_json_str = result[0]
            dom_data = json.loads(dom_json_str)

            # Check structure
            if dom_data.get("status") != "success":
                results.add_fail("DOM Extraction - Status", f"Status is {dom_data.get('status')}")
                return

            results.add_pass("DOM Extraction - Status", "Successfully extracted DOM")

            # Now test retrieve_interactive_elements with ARIA format
            interactive_json = dom_extractor.retrieve_interactive_elements(dom_json_str)
            interactive_data = json.loads(interactive_json)

            if interactive_data.get("status") != "success":
                results.add_fail("Interactive Elements - Status", f"Status is {interactive_data.get('status')}")
                return

            results.add_pass("Interactive Elements - Status", "Successfully extracted interactive elements")

            # Check ARIA format
            elements = interactive_data.get("interactive_elements", [])

            if not elements:
                results.add_fail("ARIA Format - Elements Found", "No interactive elements found")
                return

            results.add_pass("ARIA Format - Elements Found", f"Found {len(elements)} interactive elements")

            # Check first 5 elements have ARIA format
            print("\n  Sample ARIA-formatted elements:")
            for i, elem in enumerate(elements[:5]):
                if "role" in elem and "name" in elem:
                    print(f"    [{i+1}] role=\"{elem['role']}\" name=\"{elem['name'][:50]}...\"")
                else:
                    results.add_fail("ARIA Format - Missing Fields", f"Element {i} missing 'role' or 'name'")
                    return

            results.add_pass("ARIA Format - Fields Present", "All elements have 'role' and 'name' fields")

        else:
            results.add_fail("DOM Extraction - Return Type", f"Unexpected return type: {type(result)}")

    except Exception as e:
        results.add_fail("DOM Extraction - Exception", str(e))


async def test_action_navigate(page: Page):
    """Test navigate action."""
    print("\n" + "=" * 80)
    print("TEST 2: Action - Navigate")
    print("=" * 80)

    try:
        action = Action(
            action="navigate",
            args=ActionArgs(url="https://www.example.com")
        )

        result = await dispatch_action(page, action)

        print(f"  Action: {result.action}")
        print(f"  Status: {result.status}")
        print(f"  Message: {result.message}")
        print(f"  Execution Time: {result.execution_time_ms}ms")

        if result.status == "success":
            # Verify we're on the page
            current_url = page.url
            if "example.com" in current_url:
                results.add_pass("Navigate Action", f"Successfully navigated to {current_url}")
            else:
                results.add_fail("Navigate Action", f"Expected example.com, got {current_url}")
        else:
            results.add_fail("Navigate Action", f"{result.error_type}: {result.message}")

    except Exception as e:
        results.add_fail("Navigate Action - Exception", str(e))


async def test_action_click(page: Page):
    """Test click action."""
    print("\n" + "=" * 80)
    print("TEST 3: Action - Click")
    print("=" * 80)

    try:
        # Navigate to Google first
        await page.goto("https://www.google.com")
        await page.wait_for_load_state("networkidle")

        # Try to click the search box
        action = Action(
            action="click",
            args=ActionArgs(role="combobox", name="Search")
        )

        result = await dispatch_action(page, action)

        print(f"  Action: {result.action}")
        print(f"  Status: {result.status}")
        print(f"  Message: {result.message}")
        print(f"  Execution Time: {result.execution_time_ms}ms")

        if result.status == "success":
            results.add_pass("Click Action", "Successfully clicked search box")
        else:
            # Try alternate role/name
            print("  Retrying with alternate selector...")
            action2 = Action(
                action="click",
                args=ActionArgs(role="textbox", name="Search")
            )
            result2 = await dispatch_action(page, action2)

            if result2.status == "success":
                results.add_pass("Click Action", "Successfully clicked with alternate selector")
            else:
                results.add_fail("Click Action", f"{result.error_type}: {result.message}")

    except Exception as e:
        results.add_fail("Click Action - Exception", str(e))


async def test_action_type(page: Page):
    """Test type action."""
    print("\n" + "=" * 80)
    print("TEST 4: Action - Type")
    print("=" * 80)

    try:
        # Navigate to Google and click search box first
        await page.goto("https://www.google.com")
        await page.wait_for_load_state("networkidle")

        # Click search box
        await page.click('textarea[name="q"]')
        await asyncio.sleep(0.5)

        # Type text
        action = Action(
            action="type",
            args=ActionArgs(text="Hello World Test")
        )

        result = await dispatch_action(page, action)

        print(f"  Action: {result.action}")
        print(f"  Status: {result.status}")
        print(f"  Message: {result.message}")
        print(f"  Execution Time: {result.execution_time_ms}ms")

        if result.status == "success":
            # Verify text was typed
            input_value = await page.input_value('textarea[name="q"]')
            if "Hello World Test" in input_value:
                results.add_pass("Type Action", f"Successfully typed text: {input_value}")
            else:
                results.add_fail("Type Action", f"Text not found in input. Got: {input_value}")
        else:
            results.add_fail("Type Action", f"{result.error_type}: {result.message}")

    except Exception as e:
        results.add_fail("Type Action - Exception", str(e))


async def test_action_search(page: Page):
    """Test search action."""
    print("\n" + "=" * 80)
    print("TEST 5: Action - Search")
    print("=" * 80)

    try:
        # Navigate to Google
        await page.goto("https://www.google.com")
        await page.wait_for_load_state("networkidle")

        action = Action(
            action="search",
            args=ActionArgs(text="Playwright testing")
        )

        result = await dispatch_action(page, action)

        print(f"  Action: {result.action}")
        print(f"  Status: {result.status}")
        print(f"  Message: {result.message}")
        print(f"  Execution Time: {result.execution_time_ms}ms")

        if result.status == "success":
            await asyncio.sleep(2)  # Wait for search results
            current_url = page.url
            if "search" in current_url or "Playwright" in await page.content():
                results.add_pass("Search Action", "Successfully performed search")
            else:
                results.add_fail("Search Action", "Search didn't navigate to results")
        else:
            results.add_fail("Search Action", f"{result.error_type}: {result.message}")

    except Exception as e:
        results.add_fail("Search Action - Exception", str(e))


async def test_action_scroll(page: Page):
    """Test scroll action."""
    print("\n" + "=" * 80)
    print("TEST 6: Action - Scroll")
    print("=" * 80)

    try:
        # Navigate to a long page
        await page.goto("https://www.wikipedia.org")
        await page.wait_for_load_state("networkidle")

        # Get initial scroll position
        initial_y = await page.evaluate("window.scrollY")

        # Scroll down
        action = Action(
            action="scroll",
            args=ActionArgs(direction="down")
        )

        result = await dispatch_action(page, action)

        print(f"  Action: {result.action}")
        print(f"  Status: {result.status}")
        print(f"  Message: {result.message}")
        print(f"  Execution Time: {result.execution_time_ms}ms")

        if result.status == "success":
            await asyncio.sleep(0.5)
            final_y = await page.evaluate("window.scrollY")

            if final_y > initial_y:
                results.add_pass("Scroll Action", f"Scrolled from {initial_y} to {final_y}")
            else:
                results.add_fail("Scroll Action", f"Scroll position unchanged: {initial_y} -> {final_y}")
        else:
            results.add_fail("Scroll Action", f"{result.error_type}: {result.message}")

    except Exception as e:
        results.add_fail("Scroll Action - Exception", str(e))


async def test_action_press_key(page: Page):
    """Test press_key action."""
    print("\n" + "=" * 80)
    print("TEST 7: Action - Press Key")
    print("=" * 80)

    try:
        # Navigate to Google and focus search
        await page.goto("https://www.google.com")
        await page.wait_for_load_state("networkidle")
        await page.click('textarea[name="q"]')
        await page.type('textarea[name="q"]', "Test Query")
        await asyncio.sleep(0.5)

        # Press Enter
        action = Action(
            action="press_key",
            args=ActionArgs(key="Enter")
        )

        result = await dispatch_action(page, action)

        print(f"  Action: {result.action}")
        print(f"  Status: {result.status}")
        print(f"  Message: {result.message}")
        print(f"  Execution Time: {result.execution_time_ms}ms")

        if result.status == "success":
            await asyncio.sleep(2)  # Wait for navigation
            current_url = page.url
            if "search" in current_url:
                results.add_pass("Press Key Action", "Enter key triggered search")
            else:
                results.add_fail("Press Key Action", f"Enter didn't trigger search: {current_url}")
        else:
            results.add_fail("Press Key Action", f"{result.error_type}: {result.message}")

    except Exception as e:
        results.add_fail("Press Key Action - Exception", str(e))


async def test_action_wait(page: Page):
    """Test wait action."""
    print("\n" + "=" * 80)
    print("TEST 8: Action - Wait")
    print("=" * 80)

    try:
        import time

        start_time = time.time()

        action = Action(
            action="wait",
            args=ActionArgs(seconds=2.0)
        )

        result = await dispatch_action(page, action)

        elapsed_time = time.time() - start_time

        print(f"  Action: {result.action}")
        print(f"  Status: {result.status}")
        print(f"  Message: {result.message}")
        print(f"  Execution Time: {result.execution_time_ms}ms")
        print(f"  Actual Wait Time: {elapsed_time:.2f}s")

        if result.status == "success":
            # Check if wait was approximately correct (within 0.5s tolerance)
            if 1.5 <= elapsed_time <= 2.5:
                results.add_pass("Wait Action", f"Waited {elapsed_time:.2f}s (expected 2.0s)")
            else:
                results.add_fail("Wait Action", f"Wait time off: {elapsed_time:.2f}s (expected 2.0s)")
        else:
            results.add_fail("Wait Action", f"{result.error_type}: {result.message}")

    except Exception as e:
        results.add_fail("Wait Action - Exception", str(e))


async def main():
    """Run all tests."""
    print("\n" + "=" * 80)
    print("ACTION EXECUTION SYSTEM - COMPREHENSIVE TEST SUITE")
    print("=" * 80)
    print("Testing DOM Extraction + All 7 Actions")
    print("=" * 80)

    async with async_playwright() as p:
        # Launch browser
        print("\nLaunching browser...")
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            # Run all tests
            await test_dom_extraction_aria_format(page)
            await test_action_navigate(page)
            await test_action_click(page)
            await test_action_type(page)
            await test_action_search(page)
            await test_action_scroll(page)
            await test_action_press_key(page)
            await test_action_wait(page)

        finally:
            # Print summary
            results.print_summary()

            # Close browser
            await browser.close()
            print("\nBrowser closed.")


if __name__ == "__main__":
    asyncio.run(main())

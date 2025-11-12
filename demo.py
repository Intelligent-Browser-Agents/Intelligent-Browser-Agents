"""
Demo script showing usage of the action execution module
"""

import sys
from pathlib import Path

# Make absolute imports work when running this file directly
sys.path.insert(0, str(Path(__file__).parent))

import asyncio
import json

from actions import ActionCommand
from models import Target
from runner import run_action
from browser import browser_manager


async def main():
    """Run demo actions"""
    # Get test page URL
    test_file = Path(__file__).parent / "tests" / "fixtures" / "test_page.html"
    test_url = f"file://{test_file.absolute()}"
    
    print("IG Action Execution Demo")
    print("=" * 50)
    
    print("\n1. Navigating to test page...")
    nav_command = ActionCommand(
        trace_id="demo_001",
        session_id="demo_session",
        action_type="navigate_to_url",
        input_value=test_url
    )
    result = await run_action(nav_command)
    print(f"Result: {json.dumps(result.model_dump(), indent=2)}")
    
    print("\n2. Typing into name field...")
    type_command = ActionCommand(
        trace_id="demo_002",
        session_id="demo_session",
        action_type="type_input",
        target=Target(
            selector="#name-input",
            selector_type="css"
        ),
        input_value="Demo User"
    )
    result = await run_action(type_command)
    print(f"Status: {result.status}")
    if result.error:
        print(f"Error: {result.error.message}")
    else:
        print(f"Screenshot: {result.evidence.screenshot_path}")
    
    print("\n3. Clicking submit button...")
    click_command = ActionCommand(
        trace_id="demo_003",
        session_id="demo_session",
        action_type="click_element",
        target=Target(
            selector="button[type='submit']",
            selector_type="css"
        )
    )
    result = await run_action(click_command)
    print(f"Status: {result.status}")
    print(f"Timings: resolve={result.timings_ms.resolve}ms, "
          f"interact={result.timings_ms.interact}ms, "
          f"post_capture={result.timings_ms.post_capture}ms")
    
    await browser_manager.cleanup()
    print("\nDemo completed!")


if __name__ == "__main__":
    asyncio.run(main())
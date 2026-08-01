"""
Main-frame DOM snapshot tests.

Playwright removed `page.accessibility` in 1.5x. `Executor._get_real_dom_snapshot`
still called it, and the failure was swallowed into the snapshot string, so on
every step the model received:

    [DOM snapshot failed: 'Page' object has no attribute 'accessibility']

The executor was blind to the main frame for the entire run. It could only see
iframe content, which pushed it into repeated list_links/dom_search discovery,
extra retries, and the structured-output fallback (a second LLM call per step).
"""

import pytest

from agents.executor import Executor


ARIA_YAML = """
- heading "Login" [level=1]
- textbox "Username"
- textbox "Password"
- button "Sign In"
- link "Forgot password":
  - /url: "https://example.com/reset"
- combobox "Country":
  - option "US" [selected]
- generic "wrapper"
- text: some stray copy
- banner:
  - img "logo"
"""


def test_aria_snapshot_is_converted_to_role_name_lines():
    lines = Executor._format_aria_snapshot(ARIA_YAML)
    assert '[role="textbox"] "Username"' in lines
    assert '[role="textbox"] "Password"' in lines
    assert '[role="button"] "Sign In"' in lines
    assert '[role="link"] "Forgot password"' in lines
    assert '[role="combobox"] "Country"' in lines
    assert '[role="heading"] "Login"' in lines


def test_property_rows_are_not_treated_as_elements():
    """`- /url: "..."` describes the row above; it is not a clickable target."""
    lines = Executor._format_aria_snapshot(ARIA_YAML)
    assert not any("/url" in line for line in lines)
    assert not any("example.com/reset" in line for line in lines)


def test_uninteresting_roles_are_dropped():
    lines = Executor._format_aria_snapshot(ARIA_YAML)
    assert not any('role="generic"' in line for line in lines)
    assert not any('role="text"' in line for line in lines)


def test_rows_without_an_accessible_name_are_dropped():
    """A target with no name cannot be addressed by click(role, name)."""
    lines = Executor._format_aria_snapshot('- banner:\n- button\n- button "Real"')
    assert lines == ['[role="button"] "Real"']


def test_output_matches_the_format_downstream_consumers_parse():
    """Field ranking, click-target checks and the verifier all parse this shape."""
    import re

    pattern = re.compile(r'^\[role="([^"]+)"\]\s+"(.+)"$')
    for line in Executor._format_aria_snapshot(ARIA_YAML):
        assert pattern.match(line), f"unparseable line: {line!r}"


def test_line_budget_is_respected():
    yaml_text = "\n".join(f'- button "Button {i}"' for i in range(500))
    assert len(Executor._format_aria_snapshot(yaml_text, max_lines=25)) == 25


def test_empty_input_is_safe():
    assert Executor._format_aria_snapshot("") == []
    assert Executor._format_aria_snapshot(None) == []


def test_regression_executor_no_longer_calls_the_removed_api_unguarded():
    import inspect

    source = inspect.getsource(Executor._main_frame_snapshot_lines)
    # The old call must only run behind a capability check for older Playwright.
    assert "getattr(page, \"accessibility\", None)" in source
    assert "aria_snapshot()" in source


def test_regression_installed_playwright_lacks_the_old_api():
    """Pins the reason the fix exists. If this ever fails, Playwright restored
    `page.accessibility` and the fallback branch is exercisable again."""
    from playwright.async_api import Page

    assert not hasattr(Page, "accessibility"), (
        "page.accessibility is back; the compatibility branch in "
        "_main_frame_snapshot_lines now has real coverage"
    )


@pytest.mark.browser
async def test_snapshot_sees_real_page_elements(page):
    """End to end: the model must receive actual targets, not an error string."""
    await page.set_content(
        """
        <h1>Sign in</h1>
        <input aria-label="Username">
        <input aria-label="Password" type="password">
        <button>Continue</button>
        """
    )
    executor = Executor.__new__(Executor)
    snapshot = await executor._get_real_dom_snapshot(page, max_chars=4000)

    assert "DOM snapshot failed" not in snapshot
    assert '[role="textbox"] "Username"' in snapshot
    assert '[role="button"] "Continue"' in snapshot

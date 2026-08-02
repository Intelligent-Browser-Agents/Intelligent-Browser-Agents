"""
Executor-level DOM snapshot tests.

The executor's `_get_real_dom_snapshot` is a thin wrapper over the unified
producer in dom_extraction/snapshot.py (whose parsing and rendering are pinned
in test_page_snapshot.py). These tests pin what the *model* receives each step:
real targets, ARIA roles rather than tag names, iframe content, and names that
the action layer can actually resolve.

History: Playwright removed `page.accessibility` in 1.5x while the executor
still called it, so every main-frame snapshot became
`[DOM snapshot failed: ...]` and the model was blind to the main frame for the
entire run. The separate iframe walk used HTML tag names as roles and dropped
any control without aria-label/title/innerText. Phase 3 replaced both with the
single aria_snapshot-based producer.
"""

import re

import pytest

from agents.executor import Executor
from dom_extraction.snapshot import SNAPSHOT_LINE


def test_regression_installed_playwright_lacks_the_old_api():
    """Pins why the snapshot is built on aria_snapshot rather than
    page.accessibility. If this fails, Playwright restored the old API and the
    pin (plus this comment) should be revisited."""
    from playwright.async_api import Page

    assert not hasattr(Page, "accessibility"), (
        "page.accessibility is back; the aria_snapshot-only design decision "
        "in dom_extraction/snapshot.py can be revisited"
    )


def test_regression_executor_delegates_to_the_single_producer():
    """There must be exactly one snapshot pipeline. The executor building its
    own view again is how the model ended up seeing the weaker of two."""
    import inspect

    source = inspect.getsource(Executor._get_real_dom_snapshot)
    assert "capture_page_snapshot" in source
    assert "aria_snapshot" not in source


PEOPLESOFT_IFRAME = (
    "<table>"
    "<tr><td><input type='radio' name='term' id='t1'></td>"
    "<td><label for='t1'>Spring 2026</label></td></tr>"
    "<tr><td><input type='radio' name='term' id='t2'></td>"
    "<td><label for='t2'>Fall 2025</label></td></tr>"
    "</table><input type='button' value='Continue' id='cont'>"
)


@pytest.mark.browser
async def test_iframe_controls_are_visible_to_the_model(page):
    """A PeopleSoft-shaped term selector: radios and a Continue button in an iframe.

    The previous hand-rolled DOM walk dropped both. Radios and
    `<input type=button value=...>` have no aria-label, no title and no innerText,
    which were the only name sources it consulted. On the real MyUCF grades page
    the agent therefore could not see the term radios or the Continue button, kept
    falling back to dom_search, and burned its retry budget.
    """
    executor = Executor.__new__(Executor)
    await page.set_content(
        f'<h1>View My Grades</h1><iframe srcdoc="{PEOPLESOFT_IFRAME}" width="900" height="400"></iframe>'
    )
    await page.wait_for_timeout(500)

    snapshot = await executor._get_real_dom_snapshot(page, max_chars=4000)

    assert '[role="radio"] "Spring 2026"' in snapshot
    assert '[role="radio"] "Fall 2025"' in snapshot
    assert '[role="button"] "Continue"' in snapshot


@pytest.mark.browser
async def test_iframe_roles_are_aria_roles_not_html_tag_names(page):
    """`get_by_role("td")` is not valid, so tag names as roles are unclickable."""
    executor = Executor.__new__(Executor)
    await page.set_content(
        f'<h1>Grades</h1><iframe srcdoc="{PEOPLESOFT_IFRAME}" width="900" height="400"></iframe>'
    )
    await page.wait_for_timeout(500)

    snapshot = await executor._get_real_dom_snapshot(page, max_chars=4000)

    for tag in ("td", "tr", "tbody", "table", "body", "label", "div", "span"):
        assert f'role="{tag}"' not in snapshot, f"emitted HTML tag {tag!r} as an ARIA role"


@pytest.mark.browser
async def test_targets_the_snapshot_advertises_are_actually_clickable(page):
    """Every role/name pair offered to the model must resolve to a real element."""
    executor = Executor.__new__(Executor)
    await page.set_content(
        f'<h1>Grades</h1><iframe srcdoc="{PEOPLESOFT_IFRAME}" width="900" height="400"></iframe>'
    )
    await page.wait_for_timeout(500)

    snapshot = await executor._get_real_dom_snapshot(page, max_chars=4000)
    actionable = {"radio", "button", "link", "checkbox", "textbox"}

    checked = 0
    for line in snapshot.splitlines():
        match = SNAPSHOT_LINE.search(line)
        if not match or match.group("role") not in actionable:
            continue
        role, name = match.group("role"), match.group("name")
        found = 0
        for frame in page.frames:
            found += await frame.get_by_role(role, name=name).count()
        assert found > 0, f'snapshot advertised click(role={role}, name={name}) but nothing matches'
        checked += 1

    assert checked >= 3, "expected the radios and Continue button to be checked"


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


@pytest.mark.browser
async def test_snapshot_lines_parse_under_the_published_contract(page):
    """Downstream consumers extract role/name with SNAPSHOT_LINE; every element
    line the executor hands the model must satisfy it."""
    await page.set_content(
        """
        <h1>Sign in</h1>
        <input aria-label="Username">
        <button>Continue</button>
        """
    )
    executor = Executor.__new__(Executor)
    snapshot = await executor._get_real_dom_snapshot(page, max_chars=4000)

    element_lines = [l for l in snapshot.splitlines() if l.startswith("[ref=")]
    assert element_lines
    pattern = re.compile(r"^\[ref=e\d+\] ")
    for line in element_lines:
        assert pattern.match(line), f"missing ref prefix: {line!r}"
        assert SNAPSHOT_LINE.search(line), f"unparseable line: {line!r}"

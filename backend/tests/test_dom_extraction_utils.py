"""
Regression pins for the Phase 3 deletions in dom_extraction.

The old BeautifulSoup pipeline is gone; these tests keep it gone. Each pin
names the defect it prevents from coming back (see docs/IMPROVEMENT_PLAN.md,
Phase 3).
"""

import inspect
import pathlib
import sys

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
SRC_DIR = BACKEND_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pytest

from dom_extraction import dom_extractor, snapshot


def test_the_second_snapshot_pipeline_is_gone():
    """There is exactly one producer. The BS4 pipeline guessed roles from tag
    names, could not see shadow DOM or state, and its main() returned a tuple
    on success but a bare string on error, which list_links unpacked character
    by character and silently turned into []."""
    for name in (
        "get_dom_tree_and_page_screenshot",
        "retrieve_interactive_elements",
        "main",
        "list_dom_click_targets_from_interactive_json",
        "list_dom_links_from_interactive_json",
        "infer_role_from_tag",
        "extract_aria_name",
    ):
        assert not hasattr(dom_extractor, name), f"{name} came back"


def test_no_site_specific_role_promotion_anywhere():
    """dom_extractor.py:78-82 and :474-486 promoted any div whose class
    contained one of these tokens to role=button: one travel site's DOM shape
    baked into the generic extractor."""
    for module in (dom_extractor, snapshot):
        source = inspect.getsource(module)
        for token in ("hotel", "show-price", "show prices", "property-card"):
            assert token not in source, (
                f"site-specific promotion token {token!r} found in {module.__name__}"
            )


def test_no_screenshot_side_effect_and_no_pympler():
    """Every list_links call used to write a full-page PNG to a hardcoded
    screenshots\\{title}.png and discard the bytes, and size the element list
    with pympler.asizeof."""
    source = inspect.getsource(dom_extractor)
    assert ".screenshot(" not in source
    import_lines = [l for l in source.splitlines() if l.strip().startswith(("import ", "from "))]
    assert not any("pympler" in l for l in import_lines)

    requirements = (BACKEND_DIR.parent / "requirements.txt").read_text()
    assert "pympler" not in requirements


def test_get_page_text_keeps_landmarks():
    """nav/header/footer carry "Step 2 of 5" indicators and validation
    summaries; get_page_text used to decompose them."""
    source = inspect.getsource(dom_extractor.get_page_text)
    for landmark in ("'nav'", '"nav"', "'header'", '"header"', "'footer'", '"footer"'):
        assert landmark not in source, f"get_page_text strips {landmark} again"


@pytest.mark.browser
async def test_get_page_text_returns_landmark_content(page):
    await page.set_content(
        """
        <nav>Step 2 of 5</nav>
        <main>Tell us about your experience.</main>
        <footer>All fields required before continuing.</footer>
        """
    )
    text = await dom_extractor.get_page_text(page)
    assert "Step 2 of 5" in text
    assert "Tell us about your experience." in text
    assert "All fields required before continuing." in text


def test_search_dom_text_finds_snippets():
    snaps = ["URL: https://x\n\nApplication received\nThank you"]
    assert dom_extractor.search_dom_text(snaps, "application received") == ["Application received"]
    assert dom_extractor.search_dom_text(snaps, "missing") == []
    assert dom_extractor.search_dom_text([], "anything") == []

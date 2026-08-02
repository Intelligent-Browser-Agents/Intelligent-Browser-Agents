"""
Plain-text extraction from the current page.

Everything element-shaped lives in `dom_extraction.snapshot`, the single
producer of the page representation. What remains here is text: the readable
content of a page for extract_content/dom_search, and a substring search over
saved text snapshots.

Deleted from this module, deliberately:

* `get_dom_tree_and_page_screenshot` and `retrieve_interactive_elements`, the
  BeautifulSoup pipeline that guessed ARIA roles from tag names, could not see
  shadow DOM or state, and promoted divs to buttons based on one travel site's
  class names (see docs/IMPROVEMENT_PLAN.md, Phase 3, for the exact tokens).
  It also wrote a full-page PNG to a hardcoded path on every call and discarded
  the bytes, and its `main()` was annotated `tuple[str, bytes]` while returning
  a 3-tuple on success and a bare string on every error path, which callers
  then unpacked character by character.
* The `pympler.asizeof` accounting that measured those structures.
"""

from bs4 import BeautifulSoup
from playwright.async_api import Page


async def get_page_text(page: Page, max_chars: int = 15000) -> str:
    """Extract main readable text from the current page **and all iframes**.

    PeopleSoft-style portals load content in nested iframes that
    page.content() alone will miss.

    `nav`, `header` and `footer` are kept: step indicators ("Step 2 of 5"),
    validation summaries and login state live there, and stripping them hid
    exactly the signals the verifier needs.
    """
    try:
        parts: list[str] = []
        for frame in page.frames:
            try:
                html = await frame.content()
            except Exception:
                continue
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup.find_all(["script", "style"]):
                tag.decompose()
            text = (soup.get_text(separator="\n", strip=True) or "").strip()
            text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
            if text:
                parts.append(text)
        combined = "\n\n".join(parts)
        if len(combined) > max_chars:
            combined = combined[:max_chars] + "\n... (truncated)"
        return combined
    except Exception:
        try:
            raw = await page.evaluate("() => (document.body && (document.body.innerText || document.body.textContent || '').trim()) || ''")
            return (raw or "")[:max_chars]
        except Exception:
            return ""


def search_dom_text(dom_snapshots: list[str], query: str, max_results: int = 20) -> list[str]:
    """
    Simple text search over saved DOM/text snapshots (dom_cache).

    Returns short snippets containing the query for navigation or inspection.
    """
    if not query or not dom_snapshots:
        return []
    q = query.lower()
    results: list[str] = []
    for snap in dom_snapshots:
        for line in (snap or "").splitlines():
            if q in line.lower():
                results.append(line.strip())
                if len(results) >= max_results:
                    return results
    return results

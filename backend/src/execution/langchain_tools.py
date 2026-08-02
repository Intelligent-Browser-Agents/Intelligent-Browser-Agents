"""
LangChain tools for browser actions and DOM inspection.

Wraps the existing Playwright handlers so the executor can use
LLM tool-calling (bind_tools) instead of structured output, and
adds lightweight DOM navigation/search helpers.
"""

from typing import Literal, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from playwright.async_api import Page

from .actions import (
    do_click,
    do_fill,
    do_list_tabs,
    do_read_form,
    do_read_page,
    do_scroll_to,
    do_select_option,
    do_set_checkbox,
    do_upload_file,
    do_wait_for,
)
from .handlers import (
    handle_navigate,
    handle_click,
    handle_type,
    handle_search,
    handle_scroll,
    handle_press_key,
    handle_wait,
    handle_extract_content,
    handle_go_back,
)
from dom_extraction import dom_extractor
from dom_extraction.snapshot import capture_page_snapshot


# -----------------------------------------------------------------------------
# Arg schemas (LLM-facing) – one per action
# -----------------------------------------------------------------------------

class NavigateInput(BaseModel):
    """Input for navigate tool."""
    url: str = Field(description="Full URL to open (e.g. https://example.com)")


class ClickInput(BaseModel):
    """Input for click tool."""
    role: str = Field(description="ARIA role of the element (e.g. button, link, textbox)")
    name: str = Field(description="Accessible name or label of the element")
    nth: Optional[int] = Field(
        default=None,
        description=(
            "0-based index, required only when a previous attempt reported "
            "ambiguous_target because several elements share this role and name."
        ),
    )


class FillInput(BaseModel):
    """Input for fill tool."""
    role: str = Field(description="ARIA role of the field: textbox, searchbox, combobox or spinbutton")
    name: str = Field(description="Accessible name or label of the field, exactly as shown in DOM_SNAPSHOT")
    text: str = Field(description="Value to put in the field")
    nth: Optional[int] = Field(default=None, description="0-based index, only when disambiguating")


class SelectOptionInput(BaseModel):
    """Input for select_option tool."""
    role: str = Field(default="combobox", description="Usually 'combobox' for a dropdown")
    name: str = Field(description="Accessible name or label of the dropdown")
    label: Optional[str] = Field(default=None, description="Visible option text to choose (preferred)")
    value: Optional[str] = Field(default=None, description="Underlying option value, if the label is unknown")
    nth: Optional[int] = Field(default=None, description="0-based index, only when disambiguating")


class SetCheckboxInput(BaseModel):
    """Input for set_checkbox tool."""
    role: str = Field(description="checkbox, radio or switch")
    name: str = Field(description="Accessible name or label of the control")
    checked: bool = Field(default=True, description="Desired state. Setting an explicit state is idempotent, unlike a click.")
    nth: Optional[int] = Field(default=None, description="0-based index, only when disambiguating")


class UploadFileInput(BaseModel):
    """Input for upload_file tool."""
    name: Optional[str] = Field(default=None, description="Accessible name of the file input, if it has one")
    role: Optional[str] = Field(default="textbox", description="Role of the file input, if known")
    file_path: str = Field(description="Absolute path to the file on the agent host")
    nth: Optional[int] = Field(default=None, description="0-based index when the page has several file inputs")


class WaitForInput(BaseModel):
    """Input for wait_for tool."""
    role: Optional[str] = Field(default=None, description="Role of an element to wait for")
    name: Optional[str] = Field(default=None, description="Accessible name of the element to wait for")
    url_contains: Optional[str] = Field(default=None, description="Wait until the URL contains this substring")
    text_contains: Optional[str] = Field(default=None, description="Wait until this text is visible")
    seconds: float = Field(default=10.0, description="Maximum seconds to wait", gt=0, le=60)


class ScrollToInput(BaseModel):
    """Input for scroll_to tool."""
    role: str = Field(description="ARIA role of the element to bring into view")
    name: str = Field(description="Accessible name of the element")
    nth: Optional[int] = Field(default=None, description="0-based index, only when disambiguating")


class SwitchTabInput(BaseModel):
    """Input for switch_tab tool."""
    index: int = Field(description="0-based tab index from list_tabs")


class NoArgsInput(BaseModel):
    """For tools that take no arguments."""
    pass


class TypeInput(BaseModel):
    """Input for the legacy type tool."""
    text: str = Field(description="Text to type into the currently focused input")


class SearchInput(BaseModel):
    """Input for search tool."""
    text: str = Field(description="Search query to enter in the search box")


class ScrollInput(BaseModel):
    """Input for scroll tool."""
    direction: Literal["up", "down"] = Field(description="Direction to scroll the page")


class PressKeyInput(BaseModel):
    """Input for press_key tool."""
    key: str = Field(description="Key to press (e.g. Enter, Escape, Tab)")


class WaitInput(BaseModel):
    """Input for wait tool."""
    seconds: float = Field(description="Number of seconds to wait", gt=0, le=30)


class ExtractContentInput(BaseModel):
    """Input for extract_content tool (uses DOM extraction pipeline)."""
    max_chars: int = Field(default=15000, description="Max characters to extract (default 15000)", ge=500, le=50000)


class DomSearchInput(BaseModel):
    """Input for dom_search tool."""
    query: str = Field(description="Text to search for in the current page's DOM/text snapshot")
    max_results: int = Field(default=20, ge=1, le=100, description="Maximum number of matching lines/snippets to return")


class ListLinksInput(BaseModel):
    """Input for list_links tool."""
    filter_text: str | None = Field(
        default=None,
        description="Optional text to filter link names by (case-insensitive). If omitted, returns top links on the page.",
    )
    max_results: int = Field(default=30, ge=1, le=100, description="Maximum number of links to return")


class GoBackInput(BaseModel):
    """Input for go_back tool (no arguments needed)."""
    pass


class ReadPageInput(BaseModel):
    """Input for read_page tool."""
    section: int = Field(
        default=1,
        ge=1,
        description="1-based section of the page snapshot to read. The DOM_SNAPSHOT footer names the next section when more elements exist.",
    )


# -----------------------------------------------------------------------------
# Tool factory: build tools bound to a Playwright page
# -----------------------------------------------------------------------------

def get_browser_tools(page: Page) -> list[StructuredTool]:
    """
    Return a list of LangChain tools that execute browser actions using the given page.
    Use this with llm.bind_tools(tools) so the executor can use tool_calls.
    """
    async def navigate(url: str):
        return await handle_navigate(page, url)

    async def click(role: str, name: str, nth: Optional[int] = None):
        return await do_click(page, role, name, nth=nth)

    async def fill(role: str, name: str, text: str, nth: Optional[int] = None):
        return await do_fill(page, role, name, text, nth=nth)

    async def select_option(
        name: str,
        role: str = "combobox",
        label: Optional[str] = None,
        value: Optional[str] = None,
        nth: Optional[int] = None,
    ):
        return await do_select_option(page, role, name, value=value, label=label, nth=nth)

    async def set_checkbox(role: str, name: str, checked: bool = True, nth: Optional[int] = None):
        return await do_set_checkbox(page, role, name, checked=checked, nth=nth)

    async def upload_file(
        file_path: str,
        name: Optional[str] = None,
        role: Optional[str] = "textbox",
        nth: Optional[int] = None,
    ):
        return await do_upload_file(page, role, name, file_path=file_path, nth=nth)

    async def wait_for(
        role: Optional[str] = None,
        name: Optional[str] = None,
        url_contains: Optional[str] = None,
        text_contains: Optional[str] = None,
        seconds: float = 10.0,
    ):
        return await do_wait_for(
            page,
            role=role,
            name=name,
            url_contains=url_contains,
            text_contains=text_contains,
            seconds=seconds,
        )

    async def scroll_to(role: str, name: str, nth: Optional[int] = None):
        return await do_scroll_to(page, role, name, nth=nth)

    async def read_form():
        return await do_read_form(page)

    async def list_tabs():
        return await do_list_tabs(page)

    async def type_text(text: str):
        return await handle_type(page, text)

    async def search(text: str):
        return await handle_search(page, text)

    async def scroll(direction: Literal["up", "down"]):
        return await handle_scroll(page, direction)

    async def press_key(key: str):
        return await handle_press_key(page, key)

    async def wait(seconds: float):
        return await handle_wait(page, seconds)

    async def extract_content(max_chars: int = 15000):
        return await handle_extract_content(page, max_chars=max_chars)

    async def dom_search(query: str, max_results: int = 20):
        """
        Search the current page's text/DOM for a query string and return matching lines/snippets.
        """
        text = await dom_extractor.get_page_text(page, max_chars=15000)
        if not text:
            return []
        return dom_extractor.search_dom_text([f"URL: {page.url}\n\n{text}"], query=query, max_results=max_results)

    async def list_links(filter_text: str | None = None, max_results: int = 30):
        """
        List clickable targets (links, buttons, tabs, menu items) from the unified
        page snapshot, optionally filtering by accessible name.

        Every name returned resolves through get_by_role: this used to run a
        separate BeautifulSoup pipeline whose guessed names regularly failed to
        match, and whose error paths made this tool silently return [].
        """
        snapshot = await capture_page_snapshot(page)
        f = (filter_text or "").strip().lower()
        targets: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for element in snapshot.elements:
            if element.role not in {"link", "button", "tab", "menuitem"} or not element.name:
                continue
            key = (element.role, element.name.lower())
            if key in seen:
                continue
            seen.add(key)
            if f and f not in element.name.lower():
                continue
            targets.append({"role": element.role, "name": element.name, "url": snapshot.url, "title": ""})
            if len(targets) >= max_results:
                break
        return targets

    async def read_page(section: int = 1):
        return await do_read_page(page, section=section)

    async def go_back():
        return await handle_go_back(page)

    return [
        StructuredTool.from_function(
            coroutine=navigate,
            name="navigate",
            description="Navigate the browser to a URL. Use for opening a specific page or going to a search engine.",
            args_schema=NavigateInput,
        ),
        StructuredTool.from_function(
            coroutine=click,
            name="click",
            description=(
                "Click an element by its ARIA role and accessible name (e.g. button 'Submit', link 'Home'). "
                "If the result reports ambiguous_target, repeat the call with nth= to pick one. "
                "If it reports element_not_found, the message lists the targets that do exist: use one of those."
            ),
            args_schema=ClickInput,
        ),
        StructuredTool.from_function(
            coroutine=fill,
            name="fill",
            description=(
                "PREFERRED way to enter text. Put a value into a specific field named by role and "
                "accessible name, e.g. fill(role='textbox', name='Email', text='a@b.com'). The value is "
                "read back afterwards, so a readonly or masked field reports failure instead of a false "
                "success. Use this rather than `type`, which cannot say which field it means."
            ),
            args_schema=FillInput,
        ),
        StructuredTool.from_function(
            coroutine=select_option,
            name="select_option",
            description=(
                "Choose an option in a dropdown (a native <select>). Prefer label= with the visible option "
                "text. Clicking a dropdown or its options does not work; use this. If the option does not "
                "exist the result lists the ones that do."
            ),
            args_schema=SelectOptionInput,
        ),
        StructuredTool.from_function(
            coroutine=set_checkbox,
            name="set_checkbox",
            description=(
                "Set a checkbox, radio button or switch to an explicit state, e.g. "
                "set_checkbox(role='radio', name='Spring 2026', checked=True). Prefer this over click for "
                "these controls: it is idempotent and confirms the resulting state, whereas a click toggles "
                "and a retry can silently undo the previous one."
            ),
            args_schema=SetCheckboxInput,
        ),
        StructuredTool.from_function(
            coroutine=upload_file,
            name="upload_file",
            description=(
                "Attach a local file to a file input, e.g. a resume or cover letter. Pass the absolute path "
                "on the agent host. Do not try to type a path into a file field."
            ),
            args_schema=UploadFileInput,
        ),
        StructuredTool.from_function(
            coroutine=wait_for,
            name="wait_for",
            description=(
                "Wait for something observable: an element (role+name), a URL substring, or visible text. "
                "Prefer this over `wait`, which just sleeps for a guessed duration."
            ),
            args_schema=WaitForInput,
        ),
        StructuredTool.from_function(
            coroutine=read_form,
            name="read_form",
            description=(
                "List every field on the page with its current state: filled or empty, checked or unchecked, "
                "selected option, attached file, and whether it is required or readonly. Use this to find out "
                "what is still missing before submitting a form."
            ),
            args_schema=NoArgsInput,
        ),
        StructuredTool.from_function(
            coroutine=scroll_to,
            name="scroll_to",
            description="Scroll a specific element into view by role and accessible name.",
            args_schema=ScrollToInput,
        ),
        StructuredTool.from_function(
            coroutine=list_tabs,
            name="list_tabs",
            description="List open browser tabs with their index, title and URL.",
            args_schema=NoArgsInput,
        ),
        StructuredTool.from_function(
            coroutine=type_text,
            name="type",
            description=(
                "LEGACY: type into whatever is currently focused. Prefer `fill`, which names the field. "
                "Only use this when the field genuinely has no accessible name."
            ),
            args_schema=TypeInput,
        ),
        StructuredTool.from_function(
            coroutine=search,
            name="search",
            description="Enter a search query in the page's search box and submit. Prefer duckduckgo.com or bing.com unless Google is required.",
            args_schema=SearchInput,
        ),
        StructuredTool.from_function(
            coroutine=scroll,
            name="scroll",
            description="Scroll the page up or down to reveal more content.",
            args_schema=ScrollInput,
        ),
        StructuredTool.from_function(
            coroutine=press_key,
            name="press_key",
            description="Press a keyboard key (e.g. Enter, Escape, Tab, ArrowDown).",
            args_schema=PressKeyInput,
        ),
        StructuredTool.from_function(
            coroutine=wait,
            name="wait",
            description="Wait for a few seconds (e.g. for the page to load).",
            args_schema=WaitInput,
        ),
        StructuredTool.from_function(
            coroutine=extract_content,
            name="extract_content",
            description="Extract the main readable text from the current page for storage and summarization. Use when the plan step is to extract or gather information from the page (e.g. article content, key facts).",
            args_schema=ExtractContentInput,
        ),
        StructuredTool.from_function(
            coroutine=dom_search,
            name="dom_search",
            description="Search the current page's text/DOM for a phrase and return matching lines/snippets. Use to locate where specific information appears before deciding how to act.",
            args_schema=DomSearchInput,
        ),
        StructuredTool.from_function(
            coroutine=list_links,
            name="list_links",
            description="List link-like elements (role='link', name) on the current page, optionally filtered by visible text. Use to choose a link to click based on its name/title.",
            args_schema=ListLinksInput,
        ),
        StructuredTool.from_function(
            coroutine=read_page,
            name="read_page",
            description=(
                "Read a further section of the page snapshot when DOM_SNAPSHOT says more elements exist "
                "below (e.g. '... Call read_page(section=2)'). Long forms are paginated, not truncated: "
                "the fields past the budget are in later sections, not gone."
            ),
            args_schema=ReadPageInput,
        ),
        StructuredTool.from_function(
            coroutine=go_back,
            name="go_back",
            description="Go back to the previous page (browser back button). Use when you navigated to the wrong page and need to return to try a different path.",
            args_schema=GoBackInput,
        ),
    ]

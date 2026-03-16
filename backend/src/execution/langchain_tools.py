"""
LangChain tools for browser actions and DOM inspection.

Wraps the existing Playwright handlers so the executor can use
LLM tool-calling (bind_tools) instead of structured output, and
adds lightweight DOM navigation/search helpers.
"""

from typing import Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from playwright.async_api import Page

from .handlers import (
    handle_navigate,
    handle_click,
    handle_type,
    handle_search,
    handle_scroll,
    handle_press_key,
    handle_wait,
    handle_extract_content,
)
from dom_extraction import dom_extractor


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


class TypeInput(BaseModel):
    """Input for type tool."""
    text: str = Field(description="Text to type into the focused input")


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

    async def click(role: str, name: str):
        return await handle_click(page, role, name)

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
        List link-like interactive elements from the current page (role=link, name),
        optionally filtering by visible link text.
        """
        dom_json, *_ = await dom_extractor.main(page)
        interactive_json = dom_extractor.retrieve_interactive_elements(dom_json)
        return dom_extractor.list_dom_links_from_interactive_json(
            interactive_json, filter_text=filter_text, max_results=max_results
        )

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
            description="Click an element by its ARIA role and accessible name (e.g. button 'Submit', link 'Home').",
            args_schema=ClickInput,
        ),
        StructuredTool.from_function(
            coroutine=type_text,
            name="type",
            description="Type text into the currently focused input field.",
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
    ]

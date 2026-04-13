import asyncio
from playwright.async_api import async_playwright, Browser, Page, Error as PlaywrightError
from bs4 import BeautifulSoup
import json
import time
from pympler import asizeof
from pydantic import BaseModel, ValidationError
from typing import Any


class GetDOMTreeData(BaseModel):
    tool_name: str
    status: str
    url: str
    title: str
    execution_time: float 
    total_memory_usage: int 
    dom_tree_memory_usage: int 
    page_screenshot_memory_usage: int 
    page_screenshot_path: str
    dom_tree: str

class IntElementsData(BaseModel):
    tool_name: str
    status: str
    execution_time: float
    memory_usage: int
    num_of_elements: int 
    interactive_elements: list

class FuncFailed(BaseModel):
    tool_name: str
    status: str
    error: Any
    execution_time: float


def infer_role_from_tag(tag: str, attrs: dict) -> str:
    """
    Infer ARIA role from HTML tag and attributes.

    Args:
        tag: HTML tag name (e.g., 'button', 'input', 'a')
        attrs: Dictionary of HTML attributes

    Returns:
        ARIA role string (e.g., 'button', 'textbox', 'link')
    """
    # Check for explicit ARIA role first
    if 'role' in attrs:
        return attrs['role']

    # Infer from HTML tag and type
    if tag == 'button':
        return 'button'
    elif tag == 'a':
        return 'link'
    # Many portal frameworks use clickable div/span containers with onclick
    elif tag in ('div', 'span'):
        class_value = attrs.get('class', [])
        if isinstance(class_value, list):
            class_text = " ".join(str(v) for v in class_value)
        else:
            class_text = str(class_value or "")
        marker_text = " ".join([
            class_text,
            str(attrs.get('data-testid', '')),
            str(attrs.get('data-action', '')),
            str(attrs.get('data-clickable', '')),
            str(attrs.get('data-handler', '')),
        ]).lower()
        if (
            'onclick' in attrs
            or 'ng-click' in attrs
            or 'data-action' in attrs
            or attrs.get('data-clickable')
            or attrs.get('data-handler')
            or any(tok in marker_text for tok in (
                'click', 'btn', 'button', 'result', 'card', 'hotel', 'property', 'select', 'show-price', 'show prices'
            ))
        ):
            return 'button'
        return 'generic'
    elif tag == 'input':
        input_type = attrs.get('type', 'text')
        if input_type in ['text', 'email', 'password', 'tel', 'url']:
            return 'textbox'
        elif input_type == 'search':
            return 'searchbox'
        elif input_type == 'checkbox':
            return 'checkbox'
        elif input_type == 'radio':
            return 'radio'
        elif input_type == 'submit':
            return 'button'
        elif input_type == 'button':
            return 'button'
        else:
            return 'textbox'  # Default for unknown input types
    elif tag == 'textarea':
        return 'textbox'
    elif tag == 'select':
        return 'combobox'
    elif tag == 'option':
        return 'option'
    elif tag == 'label':
        return 'label'
    else:
        return tag  # Fallback to tag name


def extract_aria_name(element, attrs: dict) -> str:
    """
    Extract accessible name from element following ARIA naming priority.

    Priority order:
    1. aria-label
    2. aria-labelledby (text content of referenced element)
    3. Element text content
    4. placeholder attribute
    5. title attribute
    6. value attribute
    7. alt attribute (for images)

    Args:
        element: BeautifulSoup element
        attrs: Dictionary of HTML attributes

    Returns:
        Accessible name string, or empty string if none found
    """
    # 1. aria-label has highest priority
    if 'aria-label' in attrs:
        return attrs['aria-label'].strip()

    # 2. aria-labelledby (simplified - just use the ID as fallback)
    if 'aria-labelledby' in attrs:
        # In a full implementation, we'd look up the referenced element
        # For now, we'll skip to next option
        pass

    # 3. Text content (trimmed and cleaned)
    text_content = element.get_text(separator=' ', strip=True)
    if text_content:
        return text_content

    # 4. placeholder attribute
    if 'placeholder' in attrs:
        return attrs['placeholder'].strip()

    # 5. title attribute
    if 'title' in attrs:
        return attrs['title'].strip()

    # 6. value attribute (for buttons/inputs)
    if 'value' in attrs:
        return attrs['value'].strip()

    # 7. alt attribute (for images used as buttons)
    if 'alt' in attrs:
        return attrs['alt'].strip()

    # 8. name attribute as last resort
    if 'name' in attrs:
        return attrs['name'].strip()

    # 9. common data-* labels used in component-heavy UIs
    for key in ('data-name', 'data-label', 'data-testid', 'id'):
        value = attrs.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    return ""  # No accessible name found

async def get_dom_tree_and_page_screenshot(page: Page) -> tuple[str, bytes]:
    """
    Retrieves a webpage's DOM Tree and takes a screenshot of webpage.
    
    Args:
        browser: Playwright Browser object.
        url: URL of webpage to get DOM Tree and screenshot from.
    
    Returns:
        If Succesful:
            Tuple[0]: Webpage data, webpage's DOM Tree, and function meta data, as a JSON string.
            Tuple[1]: Screenshot of webpage in bytes.
            Tuple[2]: Loaded webpage using playwright browser.
        If Unsuccessful:
            Tool name, status, error, and execution time up to the point of failure as a JSON string.

    **Function execution time is slightly longer in actuality than calculated and returned.**
    """

    try:
        start = time.perf_counter()

        #Goes to webpage and extracts title and DOM tree
        try: 
            
            # #! Removed page because now page is passed across agents, NOT the whole browser!
            # #  This is because passing the whole browser would create new tabs for every action. 
            # #  Passing page in will allow new actions to be performed on already existing pages.
            # page = await browser.new_page()
            # await page.goto(url)
            
            title = await page.title()

            if not title or not title.strip():
                title = "page"

            # NOTE: PeopleSoft/UCF-like portals often render key navigation/login
            # elements inside iframes. `page.content()` only covers the main
            # frame, which causes `list_links` to return 0 items even when
            # the elements are visible (via accessibility snapshots).
            #
            # We concatenate HTML from all frames so downstream BeautifulSoup
            # extraction can "see" iframe content too.
            dom_parts: list[str] = []
            max_total_chars = 600_000  # prevent runaway DOM extraction
            per_frame_cap = 120_000      # avoid starving later iframes
            total_chars = 0
            for frame in page.frames:
                try:
                    frame_html = await frame.content()
                except Exception:
                    continue
                if not frame_html:
                    continue
                if len(frame_html) > per_frame_cap:
                    frame_html = frame_html[:per_frame_cap]
                dom_parts.append(f"<!-- FRAME_URL: {getattr(frame, 'url', '')} -->\n{frame_html}")
                total_chars += len(frame_html)
                if total_chars >= max_total_chars:
                    break

            dom_tree = "\n".join(dom_parts) if dom_parts else await page.content()
        except PlaywrightError as e:
            data = FuncFailed(tool_name = 'get_dom_tree_and_page_screenshot', status = 'failed', error = str(e), execution_time = time.perf_counter() - start)
            return data.model_dump_json(indent = 4)

        #Filters out chars from webpage's domain that don't abide by file naming standards
        problamatic_chars = ['*', '?', '"', "'", '&', '|', '<', '>', '$', '!', ';', '(', ')', ':', '\\', '/', '.', ' ']
            
        for char in problamatic_chars:
            title = title.replace(char, '')  
            
        file_path = f'screenshots\\{title}.png' 

        try:
            page_screenshot = await page.screenshot(path = file_path, full_page = True) #Takes screenshot of webpage and saves it to file_path
        except PlaywrightError as e:
            data = FuncFailed(tool_name = 'get_dom_tree_and_page_screenshot', status = 'failed', error = str(e), execution_time = time.perf_counter() - start)
            return data.model_dump_json(indent = 4)

        #Packages function webpage data with function metadata into a Pydantic object
        try: 
            data = GetDOMTreeData(tool_name = 'get_dom_tree_and_page_screenshot', status = 'success', url = page.url, title = title, execution_time = time.perf_counter() - start, 
                    total_memory_usage = asizeof.asizeof(dom_tree) + asizeof.asizeof(page_screenshot), dom_tree_memory_usage = asizeof.asizeof(dom_tree), 
                    page_screenshot_memory_usage = asizeof.asizeof(page_screenshot), page_screenshot_path = file_path, 
                    dom_tree = dom_tree, page = page)
        except ValidationError as e:
            data = FuncFailed(tool_name = 'get_dom_tree_and_page_screenshot', status = 'failed', error = e.json(), execution_time = time.perf_counter() - start)
            return data.model_dump_json(indent = 4)

        return data.model_dump_json(indent = 4), page_screenshot, page #Converts object to JSON
    except Exception as e:
        data = FuncFailed(tool_name = 'get_dom_tree_and_page_screenshot', status = 'failed', error = str(e), execution_time = time.perf_counter() - start)
        return data.model_dump_json(indent = 4)

    
def retrieve_interactive_elements(page_data: str) -> str:
    """
    Filters for PREDICTABLE interactive elements from a DOM Tree.

    Args:
        page_data: Webpage data, webpage's DOM Tree, and function meta data, as a JSON string (formatted as returned from get_dom_tree_and_page_screenshot).

    Returns:
        If Successful:    
            All PREDICTABLE interactive elements from a DOM Tree, and function meta data, as a JSON string.
        If Unsuccessful:
            Tool name, status, error, and execution time up to the point of failure as a JSON string.

    **Function execution time is slightly longer in actuality than calculated and returned.**
    """
    
    try:
        start = time.perf_counter()
        
        #Extracts webpages data from JSON
        page_data = json.loads(page_data)
        url = page_data['url']
        title = page_data['title']
        dom_tree = page_data['dom_tree']

        #Extracts all common interactive elements from webpages DOM tree
        soup = BeautifulSoup(dom_tree, 'html.parser')

        common_interactive_tags = ['a', 'button', 'input', 'select', 'option', 'textarea', 'label']
        interactive_elements = []

        for tag in common_interactive_tags:
            elements = soup.find_all(tag)

            for element in elements:
                # Extract ARIA role and name
                role = infer_role_from_tag(tag, element.attrs)
                name = extract_aria_name(element, element.attrs)

                # Build ARIA-formatted element
                interactive_element = {
                    'url': url,
                    'title': title,
                    'role': role,
                    'name': name,
                    'tag': tag,  # Keep tag for debugging
                    'attributes': element.attrs  # Keep raw attributes for reference
                }
                interactive_elements.append(interactive_element)

        # Handle onclick elements that might not be in common tags
        onclick_elements = soup.find_all(onclick=True)

        for element in onclick_elements:
            # Skip if already processed
            if element.name in common_interactive_tags:
                continue

            # Extract ARIA role and name
            role = infer_role_from_tag(element.name, element.attrs)
            name = extract_aria_name(element, element.attrs)

            interactive_element = {
                'url': url,
                'title': title,
                'role': role,
                'name': name,
                'tag': element.name,
                'attributes': element.attrs
            }
            interactive_elements.append(interactive_element)

        #Packages function meta data and webpage data into a Pydantic object
        try: 
            data = IntElementsData(tool_name = 'retrieve_interactive_elements', status = 'success', execution_time = time.perf_counter() - start, 
                                   memory_usage = asizeof.asizeof(interactive_elements), num_of_elements = len(interactive_elements), 
                                   interactive_elements = interactive_elements)
        except ValidationError as e:
            data = FuncFailed(tool_name = 'retrieve_interactive_elements', status = 'failed', error = e.json(), execution_time = time.perf_counter() - start)
            return data.model_dump_json(indent = 4)
        
        return data.model_dump_json(indent = 4) #Converts object to JSON
    except Exception as e:
        data = FuncFailed(tool_name = 'retrieve_interactive_elements', status = 'failed', error = str(e), execution_time = time.perf_counter() - start)
        return data.model_dump_json(indent = 4)

async def get_page_text(page: Page, max_chars: int = 15000) -> str:
    """
    Extract main readable text from the current page **and all iframes**.
    PeopleSoft-style portals load content in nested iframes that
    page.content() alone will miss.
    """
    try:
        parts: list[str] = []
        for frame in page.frames:
            try:
                html = await frame.content()
            except Exception:
                continue
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup.find_all(["script", "style", "nav", "footer", "header"]):
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


def list_dom_links_from_interactive_json(interactive_json: str, filter_text: str | None = None, max_results: int = 50) -> list[dict]:
    """
    Utility to list link-like interactive elements from retrieve_interactive_elements() output.

    Not wired as a tool yet; meant to be called from agents or tests to inspect
    the DOM in a more structured way.
    """
    try:
        data = json.loads(interactive_json)
    except Exception:
        return []
    elements = data.get("interactive_elements") or []
    out: list[dict] = []
    f = (filter_text or "").lower()
    for el in elements:
        if el.get("role") != "link":
            continue
        name = (el.get("name") or "").strip()
        if f and f not in name.lower():
            continue
        out.append({"role": el.get("role"), "name": name, "url": el.get("url"), "title": el.get("title")})
        if len(out) >= max_results:
            break
    return out


def list_dom_click_targets_from_interactive_json(
    interactive_json: str,
    filter_text: str | None = None,
    max_results: int = 50,
    roles: tuple[str, ...] = ("link", "button", "tab"),
) -> list[dict]:
    """
    List interactive elements that are suitable click targets.

    Unlike list_dom_links_from_interactive_json(), this does NOT restrict results
    to role == "link". Many portal sign-in elements (e.g. "myUCF") are buttons.
    """
    try:
        data = json.loads(interactive_json)
    except Exception:
        return []

    elements = data.get("interactive_elements") or []
    out: list[dict] = []
    f = (filter_text or "").lower()

    def _stringify_attr(value) -> str:
        if isinstance(value, list):
            return " ".join(str(v) for v in value if v)
        return str(value or "")

    def _normalize_name(raw_name: str, attrs: dict) -> str:
        name = (raw_name or "").strip()
        if name:
            return name
        for key in ("aria-label", "title", "data-name", "data-label", "name", "id"):
            value = attrs.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        testid = attrs.get("data-testid")
        if isinstance(testid, str) and testid.strip():
            human = testid.replace("-", " ").replace("_", " ").strip()
            return human[:120]
        return ""

    def _maybe_promote_generic_role(role: str, attrs: dict) -> str:
        if role != "generic":
            return role
        marker = " ".join([
            _stringify_attr(attrs.get("class")),
            _stringify_attr(attrs.get("data-testid")),
            _stringify_attr(attrs.get("data-action")),
            _stringify_attr(attrs.get("data-clickable")),
            _stringify_attr(attrs.get("data-handler")),
        ]).lower()
        if any(tok in marker for tok in ("click", "btn", "button", "result", "card", "select", "show prices", "property", "hotel")):
            return "button"
        return role

    for el in elements:
        attrs = el.get("attributes") if isinstance(el.get("attributes"), dict) else {}
        role = (el.get("role") or "").strip().lower()
        role = _maybe_promote_generic_role(role, attrs)
        if role and role not in roles:
            continue
        name = _normalize_name(el.get("name"), attrs)
        if not name:
            continue
        if f and f not in name.lower():
            continue
        out.append(
            {
                "role": role,
                "name": name,
                "url": el.get("url"),
                "title": el.get("title"),
            }
        )
        if len(out) >= max_results:
            break

    return out


async def main(page: Page):

    print("DOM EXTRACTION CALLED!")
    # uses page (includes url) to extract DOM
    return await get_dom_tree_and_page_screenshot(page)


if __name__ == "__main__": 
    asyncio.run(main())
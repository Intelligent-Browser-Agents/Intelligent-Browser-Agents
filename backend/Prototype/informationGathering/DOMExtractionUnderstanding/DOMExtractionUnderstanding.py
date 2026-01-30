import asyncio
from playwright.async_api import async_playwright, Browser, Error as PlaywrightError
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

class FuncFailed(BaseException):
    tool_name: str
    status: str
    error: Exception
    execution_time: float

async def get_dom_tree_and_page_screenshot(browser: Browser, url: str) -> tuple[str, bytes]:
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
            page = await browser.new_page()
            await page.goto(url)
            title = await page.title()
            dom_tree = await page.content()
        except PlaywrightError as e:
            data = FuncFailed(tool_name = 'get_dom_tree_and_page_screenshot', status = 'failed', error = e, execution_time = time.perf_counter() - start)
            return data.model_dump_json(indent = 4)

        #Filters out chars from webpage's domain that don't abide by file naming standards
        problamatic_chars = ['*', '?', '"', "'", '&', '|', '<', '>', '$', '!', ';', '(', ')', ':', '\\', '/', '.', ' ']
            
        for char in problamatic_chars:
            title = title.replace(char, '')  
            
        file_path = f'screenshots\\{title}.png' 

        try:
            page_screenshot = await page.screenshot(path = file_path, full_page = True) #Takes screenshot of webpage and saves it to file_path
        except PlaywrightError as e:
            data = FuncFailed(tool_name = 'get_dom_tree_and_page_screenshot', status = 'failed', error = e, execution_time = time.perf_counter() - start)
            return data.model_dump_json(indent = 4)

        #Packages function webpage data with function metadata into a Pydantic object
        try: 
            data = GetDOMTreeData(tool_name = 'get_dom_tree_and_page_screenshot', status = 'success', url = url, title = title, execution_time = time.perf_counter() - start, 
                    total_memory_usage = asizeof.asizeof(dom_tree) + asizeof.asizeof(page_screenshot), dom_tree_memory_usage = asizeof.asizeof(dom_tree), 
                    page_screenshot_memory_usage = asizeof.asizeof(page_screenshot), page_screenshot_path = file_path, 
                    dom_tree = dom_tree, page = page)
        except ValidationError as e:
            data = FuncFailed(tool_name = 'get_dom_tree_and_page_screenshot', status = 'failed', error = e.json(), execution_time = time.perf_counter() - start)
            return data.model_dump_json(indent = 4)

        return data.model_dump_json(indent = 4), page_screenshot, page #Converts object to JSON
    except Exception as e:
        data = FuncFailed(tool_name = 'get_dom_tree_and_page_screenshot', status = 'failed', error = e, execution_time = time.perf_counter() - start)
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
                interactive_element = {'url': url, 'title': title, 'tag': tag, 'text': element.text, 'attributes': element.attrs}
                interactive_elements.append(interactive_element)

        onclick_elements = soup.find_all(onclick = True)

        for element in onclick_elements:
            interactive_element = {'url': url, 'title': title, 'tag': tag, 'text': element.text, 'attributes': element.attrs}
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
        data = FuncFailed(tool_name = 'retrieve_interactive_elements', status = 'failed', error = e, execution_time = time.perf_counter() - start)
        return data.model_dump_json(indent = 4)

async def main(browser):
    # async with async_playwright() as p:
        # browser = await p.chromium.launch(headless=False, slow_mo=50)
    print("testing main working")
    result = await get_dom_tree_and_page_screenshot(browser, 'https://www.target.com/')
    print(retrieve_interactive_elements(result[0]))


if __name__ == "__main__": 
    asyncio.run(main())
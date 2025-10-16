# Edwin Villanueva
#-------------------------------------------------------------------------#@
# This program acts as a starting point for retrieving DOM from a website #
#-------------------------------------------------------------------------#@

import asyncio
import json
import os
from playwright.async_api import async_playwright


async def extract_dom(url: str, save_as: str, output_dir = "DOM_output", ):

    os.makedirs(output_dir, exist_ok=True)

    async with async_playwright() as p:

        # launch the browser
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # go to the page you want to visit and save its content
        print(f"Visiting {url}...")
        await page.goto(url, wait_until = "networkidle")
        html_content = await page.content()

        # this is long as shit, but proof if you wanna see the DOM for yourself...      
        # print(f"=======================DOM content======================\n{html_content}")

        # TODO: feed 'html_content' to openai or whatever we use to decide which actions to take from there
    
        await browser.close()

if __name__ == "__main__":

    url = "https://www.google.com"
    asyncio.run(extract_dom(url, save_as = "html"))

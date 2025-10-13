import sys
print("Interpreter actually running:", sys.executable)


import asyncio
from playwright.async_api import async_playwright, Playwright

async def run(playwright: Playwright):
    
    # define the browser you want to use
    chromium = playwright.chromium  # You can also use others like 'firefox' or 'edge' (but don't use edge lmfao)
    
    # launch the browser (asyncronousy ooooooh)
    browser = await chromium.launch()
    
    # create a new suerpage on the newly loaded browser
    page = await browser.new_page()
    
    # send the agent to the website of your choice
    website = "http://www.google.com"
    await page.goto(website)
    
    # === do whatever else you want before ending ===
    
    # end the browsing session
    await browser.close()
    
    
async def main():
    async with async_playwright() as playwright:
        
        await run(playwright)
        
# start the program
asyncio.run(main())
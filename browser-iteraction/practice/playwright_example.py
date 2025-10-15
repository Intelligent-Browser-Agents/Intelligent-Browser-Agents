import asyncio
from playwright.async_api import async_playwright
import pyautogui

async def main():
    async with async_playwright() as p: 
        
        # launch the browser
        browser = await p.firefox.launch(headless=False)
        page = await browser.new_page()
        
        # go to google
        await page.goto("https://www.google.com")
        
        # if "accept cookies" popup appears, accept them idgaf I just want it gone
        try: 
            await page.locator("button:has-text('Accept all')").click(timeout=3000)
        except:
            pass    # if no prompt, even better
        
        # click into the search box
        await page.click("textarea[name='q']")
        
        # wait a moment before typing 
        await asyncio.sleep(1)
        
        # type the text (0.3 seconds between keystrokes)
        pyautogui.typewrite("Playwright python", interval=0.3)
        
        # press enter
        await page.keyboard.press("Enter")
        
        # wait for results to load
        await page.wait_for_selector("h3")
        
        print("=== SEARCH COMPLETED! ===")
        await browser.close()
    
asyncio.run(main())
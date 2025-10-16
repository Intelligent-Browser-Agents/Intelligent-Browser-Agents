# Edwin Villanueva
#----------------------------------------------------------------------------------------#
# This program is designed to act as a guide for us to implement our agent's execution.  #
# Using playwright, pyautogui, and eventually, detecting the OS, we can safely create    #
# a Chromium tab that can search on google without triggering human verification.        #
#----------------------------------------------------------------------------------------#
import asyncio
import pyautogui
from playwright.async_api import async_playwright
import random
from pathlib import Path

# ensures each letter is typed at random intervals
async def type_in_random_intervals(message):
    for ch in message:
        pyautogui.typewrite(ch)
        await asyncio.sleep(random.uniform(0.02, 0.2))


async def main():
    async with async_playwright() as p:
      
        # gather the user's chrome profile if it exists
        # NOTE: The file location is different based on the operating system the user uses
            # TODO: Implement switch case for different operating systems
        project_profile = Path.cwd() / "chrome_profile"
        project_profile.mkdir(exist_ok=True)

        # open a new browser window with the user's profile *starting with google for testing*
        async with async_playwright() as p:
            browser = await p.chromium.launch_persistent_context(
                user_data_dir=str(project_profile),
                headless=False,
                args=["--disable-blink-features=AutomationControlled"]
            )
            page = await browser.new_page()
            await page.goto("https://google.com")

        # accept cookies if prompted
        try:
            await page.locator("button:has-text('Accept all')").click(timeout=3000)
        except: 
            pass

        await asyncio.sleep(1)
        
        # search for something (is as human of a way as you can)
        await page.click("textarea[name='q']")
        await asyncio.sleep(1)
        query = "playwright python"
        await type_in_random_intervals(query)
        pyautogui.press("Enter")

        await page.wait_for_selector("h3")
        print("=== SEARCH COMPLETED ===")


        await browser.close()

asyncio.run(main())
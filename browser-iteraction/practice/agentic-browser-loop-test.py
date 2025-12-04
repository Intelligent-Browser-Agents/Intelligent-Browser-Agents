from openai import OpenAI
from dotenv import load_dotenv
import asyncio
import pyautogui
from playwright.async_api import async_playwright, Playwright
import random
from pathlib import Path
# from agentic-tools import * # for tools for the agent to call for future implementation

#----------------------------------------------------------------------------------------#
# This program is designed to act as a test for us to implement our agent's execution    #
# Using playwright, pyautogui, and OpenAI's API to generate plans for task execution.    #
# Combines ideas from playwright_example and LLM input loop.                             #
#----------------------------------------------------------------------------------------#
load_dotenv()
client = OpenAI()

system_prompt = """
You are a web browsing agent. You will recieve input from a user who would like to perform an action on the internet. 
Listen to the user's input and based on their request, generate a response that you think reflects the best next step within the web browser using available tools.
"""

# === type in random intervals function 
# ensures each letter is typed at random intervals
async def type_in_random_intervals(message):
    for ch in message:
        pyautogui.typewrite(ch)
        await asyncio.sleep(random.uniform(0.02, 0.2))


# === generate llm input function ===
# generates response to the current page and state through OpenAI's gpt o4 mini model API
def generate_llm_input(current_page):
    response = client.responses.create (
        model = "o4-mini-2025-04-16",
        input = f"based on the current page: {current_page}, come up with a next step to perform based on the user's inital message"
    )
    
    print(response.output_text)
    return response.output_text


# === (driver) main function ===
# asks the user for initial input
async def main():

    # take initial user input and send it to the model
    # user_input = input("What would you like out of this browsing session?\nYour input: ")

    # the site which will change over time as we continue to navigate the internet
    web_url = "https://google.com"
    
    ## generate initial input to bring us to the first page on the browser 
    # response = client.responses.create(
    #     model = "o4-mini-2025-04-16", 
    #     input = [
    #         # system input
    #         {"role": "system", "content": system_prompt},
    #         # user input
    #         {"role": "user", "content": user_input}
    #     ]
    # )
    
    # start browser off at Google.com
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        await page.goto(web_url)


        # based on the current first page we are on, generate a list of actions (in order from first to last) that will bring us to the next step of completion
        #? HOW ARE WE SENDING THIS WITHOUT COLLECTING DOM INFO FROM BI?

        # for now, extract compressed DOM 
        print("Getting DOM elements from current page...")
        ax_tree = await page.accessibility.snapshot(root=None, interesting_only=True)
        print(ax_tree)
        print(f"DOM recieved from {web_url}!")

        # once DOM is recieved, 

if __name__ == "__main__": 
    asyncio.run(main())
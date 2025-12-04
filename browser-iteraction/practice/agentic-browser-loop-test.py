from openai import OpenAI
from dotenv import load_dotenv
import asyncio
import pyautogui
from playwright.async_api import async_playwright
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
Listen to the user's input and based on their request, generate a response that you think reflects the best next 
"""

# === type in random intervals function 
# ensures each letter is typed at random intervals
async def type_in_random_intervals(message):
    for ch in message:
        pyautogui.typewrite(ch)
        await asyncio.sleep(random.uniform(0.02, 0.2))
# ===

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
def main(): 
    
    # take user input and send it to the model
    user_input = input("What would you like out of this browsing session?\nYour input: ")
    
    
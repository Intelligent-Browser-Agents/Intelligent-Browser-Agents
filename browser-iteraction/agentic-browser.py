from openai import OpenAI
from dotenv import load_dotenv
import asyncio
import pyautogui
from playwright.async_api import async_playwright, Playwright
import random
from pathlib import Path
import json
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

# based on the user's initial request, comes up with the ultimate goal of the agent, and hopefully a step by s
main_goal_prompt = """
You are the Main Goal Generator for an intelligent browser agent.

Your job:
- Take a user's natural-language request.
- Clarify and restate the request as a single, concise, explicit browsing goal.
- Make the goal actionable, specific, and free of ambiguity.

Output rules:
- Do NOT include steps.
- Do NOT mention tools or actions.
- Only output the clarified final goal in one sentence.

Examples:
User: "I want to find Nike shoes on sale."
Goal: "Find discounted Nike shoes available for purchase online."

User: "I need to check the weather in Boston tomorrow."
Goal: "Display tomorrow's weather forecast for Boston."

User: "Look up my favorite actor’s birthday."
Goal: "Find and display the birthdate of the user’s favorite actor."

Your turn:
"""

# orchestration - comes up with steps to achieve the main goal based on user input and main goal generated.
steps_prompt = """
You are the Orchestration Agent for a browser automation system.

Your responsibility:
- Given a final goal, create a numbered list of high-level steps.
- Assume the agent starts on https://google.com.
- Steps should describe WHAT to do, not HOW.
- Output 3–8 steps maximum.

Rules:
- Do NOT include technical details (selectors, DOM, coordinates).
- Do NOT guess about the current page; assume only Google.com as the start.
- All steps must logically lead toward accomplishing the final goal.

Format:
1. Step 1
2. Step 2
3. Step 3
...

Example:
Goal: "Find discounted Nike shoes available for purchase online."
Steps:
1. Search Google for "Nike shoes on sale".
2. Open a reputable shopping website from the search results.
3. Filter the results to show discounted items.
4. Identify several discounted Nike shoe options.

Now generate the steps for the provided goal.
"""

# prompts the agent to choose the best tools from the tools_to_call list based on all information provided
current_step_prompt = """
You are the Action Selection Agent for an intelligent web browser agent.

Inputs you receive:
- The user's original request.
- The clarified main goal.
- The high-level plan for achieving the goal.
- A compressed accessibility-based DOM snapshot of the CURRENT page.
- A list of available browser tools (click, type, search, scroll, etc.).

Your job:
- Decide the SINGLE next action the agent should take.
- The action must be realistic based on the DOM you see.
- If the next step from the plan is not yet possible, determine the action required to move toward it.
- If needed, extract information from the page.

Output format (JSON ONLY):
{
  "action": "<click | type | navigate | scroll | press_key | wait>",
  "target": "<human-readable element name OR url OR text to type>",
  "reasoning": "<one short sentence explaining why>"
}

Rules:
- Only describe ONE action and its target.
- Base your choice on what is actually present in the DOM.
- Do NOT hallucinate elements that do not appear.
- Keep reasoning short and factual.

Begin.
"""

# list of tools and functions this agent is able to perform on the web browser (by name, not functionality)
tools_to_call = """
Available browser tools:

1. navigate(url)
   - Opens the given URL.

2. click(element_name)
   - Clicks a visible UI element referenced by its role or name.

3. type(text)
   - Types text into the currently focused input box.

4. search(query)
   - Shortcut for typing into Google’s search box and submitting.

5. scroll(direction)
   - Scrolls the page up or down.

6. press_key(key)
   - Presses a single keyboard key.

7. wait(seconds)
   - Pause execution for a short time.

The agent may only choose from these tools.
"""

# === type in random intervals function ===
# ensures each letter is typed at random intervals
async def type_in_random_intervals(message):
    for ch in message:
        pyautogui.typewrite(ch)
        await asyncio.sleep(random.uniform(0.02, 0.2))

# parses steps from steps agent output to create array from steps
def parse_numbered_steps(text):
    steps = []
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith(tuple(str(i) for i in range(1, 10))):
            # Example: "1. Search Google for..." → keep text after "1. "
            step_text = line.split(".", 1)[1].strip()
            steps.append(step_text)
    return steps

# === execute action function ===
# executes action that model decided on
async def execute_action(page, action, target):
    """
    Executes the LLM-selected action using Playwright.
    More actions will be developed in future versions of Intelligent Browser Agents
    """

    # 1. NAVIGATE
    if action == "navigate":
        await page.goto(target)
        return

    # 2. CLICK
    if action == "click":
        # We search for an element by ROLE or NAME
        try:
            await page.get_by_role("button", name=target).click(timeout=3000)
            return
        except:
            pass
        try:
            await page.get_by_role("link", name=target).click(timeout=3000)
            return
        except:
            pass

        print(f"[!] Could not click target: {target}")
        return

    # 3. TYPE
    if action == "type":
        await page.keyboard.type(target)
        return

    # 4. SEARCH
    if action == "search":
        # Focus the primary search box if available
        try:
            search_box = page.get_by_role("combobox", name="Search")
            await search_box.click()
            await search_box.fill(target)
            await page.keyboard.press("Enter")
            return
        except:
            # fallback: type in whatever is focused
            await page.keyboard.type(target)
            await page.keyboard.press("Enter")
            return

    # 5. SCROLL
    if action == "scroll":
        direction = target.lower()
        if direction == "down":
            await page.mouse.wheel(0, 800)
        else:
            await page.mouse.wheel(0, -800)
        return

    # 6. PRESS_KEY
    if action == "press_key":
        await page.keyboard.press(target)
        return

    # 7. WAIT
    if action == "wait":
        await asyncio.sleep(float(target))
        return

    print(f"[!] Unknown action: {action}")



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
    user_input = input("What would you like out of this browsing session?\nYour input: ")

    # initialize site to start from. the site which will change over time as we continue to navigate the internet
    web_url = "https://google.com"
    
    # generate the main goal of the session based on the user's initial input 
    main_goal = client.responses.create(
        model = "o4-mini-2025-04-16", 
        input = [
            # system input
            {"role": "system", "content": main_goal_prompt},
            # user input
            {"role": "user", "content": user_input}
        ]
    )

    #! test 
    print(main_goal.output_text)
 
    # generate a list of steps from start to finish for the agent to take from google.com to the end of the session 
    llm_steps = client.responses.create (
        model = "o4-mini-2025-04-16", 
        input = [
            {"role": "system", "content": steps_prompt},
            {"role": "user", "content": main_goal.output_text},
        ]
    )


    # start browser off at Google.com
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        await page.goto(web_url)
    
        # make the steps list into an array that we can iterate through
        steps_list = parse_numbered_steps(llm_steps.output_text)
        print("Parsed steps: ", steps_list)

        #! == step performing loop ==

        i = 0   # step index
        for step in steps_list:

            # TEST PRINT 
            print(f" =====  Step {i}: ", step, " =====")

            # for now, extract compressed DOM 
            # print("Getting DOM elements from current page...")
            compressed_dom = await page.accessibility.snapshot(root=None, interesting_only=True)
            compressed_dom_str = json.dumps(compressed_dom, indent=2)
            # print(compressed_dom)
            print(f"Compressed DOM recieved from {web_url}!")

            # based on the current page we are on, generate a list of actions (in order from first to last) that will bring us to the next step of completion
            # todo: come up with a list of actions to take to complete this current step

            # once compressed DOM is recieved, feed it to LLM and ask it, based on the user's initial query, what the next steps are going to be?
            current_step = client.responses.create(
                model = "o4-mini-2025-04-16",
                input = [
                    {"role": "system", "content": current_step_prompt},
                    {"role": "system", "content": tools_to_call},
                    {"role": "system", "content": f"MAIN GOAL: {main_goal.output_text}"},
                    {"role": "system", "content": f"PLAN: {step}"},
                    {"role": "system", "content": f"DOM: {compressed_dom_str}"},
                    {"role": "user",   "content": user_input}
                ]
            )

            # Parse JSON
            try:
                action_data = json.loads(current_step.output_text)
            except:
                print("[!] LLM output is not valid JSON")
                print(current_step.output_text)
                continue

            action = action_data.get("action")
            target = action_data.get("target")
            reasoning = action_data.get("reasoning")

            print(f"[*] TOOL: {action}")
            print(f"[*] TARGET: {target}")
            print(f"[*] REASONING: {reasoning}")

            # EXECUTE THE ACTION
            await execute_action(page, action, target)

            # optional: small wait to let the page update
            await asyncio.sleep(2)
            print()

            i += 1

if __name__ == "__main__": 
    asyncio.run(main())
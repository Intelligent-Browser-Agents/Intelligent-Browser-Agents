"""
Execution Agent
Translates high-level plan steps into specific browser actions.
"""

from execution import Action, dispatch_action, ActionArgs
from langchain_core.messages import SystemMessage, HumanMessage
from schema import ExecutionResult
from state import ProjectState
from models import Models
from prompt_loader import get_execution_prompt
from informationGathering.DOMExtractionUnderstanding import DOMExtractionUnderstanding

from execution.handlers import handle_type

print("=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-INSIDE OF EXECUTOR: GENERAL=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-")

class Executor:
    """
    LLM-powered Executor that translates plan steps into browser actions.
    Uses the execution prompt from the prompts directory.
    """
    
    # sets up agent's llm and prompt to be used
    def __init__(self, runtime):
        print("=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-INSIDE OF EXECUTOR: __init__=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-")
        self.llm = Models.executor(ExecutionResult)
        # Load the execution prompt from the prompts directory
        self.system_prompt = get_execution_prompt()
        self.runtime = runtime


    async def __call__(self, state: ProjectState) -> dict:
        print("=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-INSIDE OF EXECUTOR: __call__=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-")
        
        # get page instance for executor to use
        page = self.runtime.get("page")
        if page is None: 
            raise RuntimeError("[ERROR]: Executor called without a Playwright page!")
        
        # initialize status values
        current_task = state.get("current_task", "No task specified")
        current_url = state.get("current_url", "unknown")
        current_plan = state.get("current_plan", [])
        user_intent = self._get_user_intent(state)
        
        # Build the context following the prompt's expected inputs
        context = f"""
        MAIN_GOAL: {user_intent}

        PLAN_STEP: {current_task}

        URL: {current_url}

        DOM_SNAPSHOT:
        {self._get_simulated_dom(current_url, current_task)}

        ALLOWED_TOOLS: navigate, click, type, search, scroll, press_key, wait

        Translate this plan step into a specific browser action.
        """

        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=context)
        ]

        action: ExecutionResult = self.llm.invoke(messages)
        
        # #! TEST
        # print("@#@#@@#@##EXECUTION RESULT@#@#@#@#@#@#@#@#@#@")
        # print(ExecutionResult)

        # Build execution log
        args_str = []
        if action.args.url:
            args_str.append(f"url={action.args.url}")
        if action.args.role:
            args_str.append(f"role={action.args.role}")
        if action.args.name:
            args_str.append(f"name={action.args.name}")
        if action.args.text:
            args_str.append(f"text={action.args.text}")
        if action.args.direction:
            args_str.append(f"direction={action.args.direction}")
        if action.args.key:
            args_str.append(f"key={action.args.key}")
        if action.args.seconds:
            args_str.append(f"seconds={action.args.seconds}")
        
        execution_log = (
            f"[Executor] Action: {action.action}\n"
            f"[Executor] Args: {', '.join(args_str) or 'None'}\n"
            f"[Executor] Status: {action.status}\n"
            f"[Executor] Message: {action.message}"
        )
        
        if action.status == "failure":
            execution_log += f"\n[Executor] Error Type: {action.error_type}"
        
        # Executing URL change for navigation actions
        new_url = current_url
        if action.action == "navigate" and action.args.url:
            new_url = action.args.url
            
            # run navigate action using DOMExtractionUnderstanding
            result = await DOMExtractionUnderstanding.main(page)
            action = Action(action="navigate", args=ActionArgs(url=new_url))
            result = await dispatch_action(result[2], action)
            print("[executor - navigate result]: ", result) # test print

        # Executing click handler (with fake input for 'role' and 'name')
        if action.action == "click": 
 
            #!!! role and name return None as it currently stands due to LLM output. fix this!
            # # check if role and name are sent in properly
            # if not action.args.role or not action.args.name: 
            #     raise RuntimeError("[Executor Error] Click action produced without role or name....\n'role': {action.args.role}\n'name': {action.args.name}")

            # HARDCODING FOR TEST on https://google.com
            role = "textbox"    # should be action.args.role
            name = "Search"     # should be

            # run click action
            result = await DOMExtractionUnderstanding.main(page)
            # ===== WARNING: hardcoded role and name values for now!! =====
            action = Action(action="click", args=ActionArgs(role=role, name=name))
            result = await dispatch_action(result[2], action)
            print("[executor - click result]: ", result) # test print


        # Executing click handler (with fake input for 'text')
        if action == "type": 

            # # check if text is sent in properly
            # if not action.args.text: 
            #     raise RuntimeError("[Executor Error] Type action produced without text....\n'text': {action.args.text}}")

            # HARDCODING FOR TEST on https://google.com
            text = "University of Central Florida" # should be action.args.text

            # run type action
            result = await DOMExtractionUnderstanding.main(page)
            # ===== WARNING: hardcoded text for now!! =====
            action = Action(action="type", args=ActionArgs(text=text))
            result = await dispatch_action(result[2], action)
            print("[executor - type result]: ", result) # test print


        # Execution of the search handler
        if action == "search": 
            # # check if query is sent in properly
            # if not action.args.query: 
            #     raise RuntimeError("[Executor Error] Search action produced without query....\n'query': {action.args.query}}")

            # HARDCODING FOR TEST on https://google.com
            query = "this is a test query" # should be action.args.query

            # run type action
            result = await DOMExtractionUnderstanding.main(page)
            # ===== WARNING: hardcoded query for now!! =====
            action = Action(action="search", args=ActionArgs(query=query))
            result = await dispatch_action(result[2], action)
            print("[executor - search result]: ", result) # test print

        # Execution of the scroll handler
        if action == "scroll": 
            # # check if direction is sent in properly
            # if not action.args.direction: 
            #     raise RuntimeError("[Executor Error] scroll action produced without direction....\n'direction': {action.args.direction}}")

            # HARDCODING FOR TEST on https://google.com
            direction = "down" # should be action.args.direction

            # run type action
            result = await DOMExtractionUnderstanding.main(page)
            # ===== WARNING: hardcoded direction for now!! =====
            action = Action(action="scroll", args=ActionArgs(direction=direction))
            result = await dispatch_action(result[2], action)
            print("[executor - scroll result]: ", result) # test print


        # Execution of the press_key handler
        if action == "press_key": 
            # # check if key is sent in properly
            # if not action.args.key: 
            #     raise RuntimeError("[Executor Error] press_key action produced without key....\n'key': {action.args.key}}")

            # HARDCODING FOR TEST on https://google.com
            key = "Enter" # should be action.args.seconds

            # run type action
            result = await DOMExtractionUnderstanding.main(page)
            # ===== WARNING: hardcoded seconds for now!! =====
            action = Action(action="press_key", args=ActionArgs(key=key))
            result = await dispatch_action(result[2], action)
            print("[executor - press_key result]: ", result) # test print



        # Execution of the wait handler
        if action == "wait": 
            # # check if seconds is sent in properly
            # if not action.args.seconds: 
            #     raise RuntimeError("[Executor Error] Wait action produced without seconds....\n'seconds': {action.args.seconds}}")

            # HARDCODING FOR TEST on https://google.com
            seconds = 5.0 # should be action.args.seconds

            # run type action
            result = await DOMExtractionUnderstanding.main(page)
            # ===== WARNING: hardcoded seconds for now!! =====
            action = Action(action="wait", args=ActionArgs(seconds=seconds))
            result = await dispatch_action(result[2], action)
            print("[executor - wait result]: ", result) # test print



        # # hardcoded simulation of the click action
        # elif action.action == "click" and "login" in current_task.lower():
        #     if "my.ucf" in current_url:
        #         new_url = "https://my.ucf.edu/dashboard"
        
        return {
            "number_of_transactions": state.get("number_of_transactions", 0) + 1,
            "reasoning_log": [execution_log],
            "current_url": new_url,
        }
    



    def _get_user_intent(self, state: ProjectState) -> str:
        print("=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-INSIDE OF EXECUTOR: _get_user_intent=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-")

        """Extract user intent from messages."""
        user_message = state["messages"][0] if state["messages"] else None
        if isinstance(user_message, dict):
            return user_message.get("content", "Unknown intent")
        elif hasattr(user_message, "content"):
            return user_message.content
        return str(user_message) if user_message else "Unknown intent"
    



    # hardcoded example DOM
    def _get_simulated_dom(self, url: str, task: str) -> str:
        print("=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-INSIDE OF EXECUTOR: _get_simulated_dom=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-")

        """Generate simulated DOM snapshot for testing."""
        
        if "ucf" in url.lower() or "login" in task.lower():
            return """
            [role="navigation"] "Main Navigation"
            [role="link"] "Home"
            [role="link"] "myUCF Login"
            [role="link"] "Academics"
            [role="link"] "Student Services"

            [role="main"]
            [role="heading"] "Welcome to UCF"
            [role="textbox"] "username" placeholder="Enter your NID"
            [role="textbox"] "password" placeholder="Enter your password"
            [role="button"] "Sign In"
            [role="link"] "Forgot Password?"
            """
        else:
            return f"""
            [role="navigation"] "Site Navigation"
            [role="link"] "Home"
            [role="link"] "About"
            [role="link"] "Contact"

            [role="main"]
            [role="heading"] "Page Content"
            [role="button"] "Submit"
            [role="textbox"] "Search"
            """

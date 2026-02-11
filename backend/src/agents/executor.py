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
from dom_extraction import dom_extractor

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

        llm_action: ExecutionResult = self.llm.invoke(messages)
        
        # Initialize result tracking
        new_url = current_url
        dispatch_result = None
        actual_action = None
        actual_args = {}
        
        # Executing URL change for navigation actions
        if llm_action.action == "navigate" and llm_action.args.url:
            new_url = llm_action.args.url
            actual_action = "navigate"
            actual_args = {"url": new_url}
            
            # run navigate action using DOMExtractionUnderstanding
            dom_result = await dom_extractor.main(page)
            action_obj = Action(action="navigate", args=ActionArgs(url=new_url))
            dispatch_result = await dispatch_action(dom_result[2], action_obj)
            print("[executor - navigate result]: ", dispatch_result)

        # Executing click handler (with fake input for 'role' and 'name')
        elif llm_action.action == "click": 
            # HARDCODING FOR TEST on https://google.com
            # TODO: Use llm_action.args.role and llm_action.args.name when LLM output is fixed
            role = llm_action.args.role or "textbox"
            name = llm_action.args.name or "Search"
            actual_action = "click"
            actual_args = {"role": role, "name": name}

            # run click action
            dom_result = await dom_extractor.main(page)
            action_obj = Action(action="click", args=ActionArgs(role=role, name=name))
            dispatch_result = await dispatch_action(dom_result[2], action_obj)
            print("[executor - click result]: ", dispatch_result)

        # Executing type handler
        elif llm_action.action == "type": 
            # HARDCODING FOR TEST on https://google.com
            # TODO: Use llm_action.args.text when LLM output is fixed
            text = llm_action.args.text or "University of Central Florida"
            actual_action = "type"
            actual_args = {"text": text}

            # run type action
            dom_result = await dom_extractor.main(page)
            action_obj = Action(action="type", args=ActionArgs(text=text))
            dispatch_result = await dispatch_action(dom_result[2], action_obj)
            print("[executor - type result]: ", dispatch_result)

        # Execution of the scroll handler
        elif llm_action.action == "scroll": 
            # Use LLM's direction if provided, otherwise default to "down"
            direction = llm_action.args.direction or "down"
            actual_action = "scroll"
            actual_args = {"direction": direction}

            # run scroll action
            dom_result = await dom_extractor.main(page)
            action_obj = Action(action="scroll", args=ActionArgs(direction=direction))
            dispatch_result = await dispatch_action(dom_result[2], action_obj)
            print("[executor - scroll result]: ", dispatch_result)

        # Execution of the press_key handler
        elif llm_action.action == "press_key": 
            # Use LLM's key if provided, otherwise default to "Enter"
            key = llm_action.args.key or "Enter"
            actual_action = "press_key"
            actual_args = {"key": key}

            # run press_key action
            dom_result = await dom_extractor.main(page)
            action_obj = Action(action="press_key", args=ActionArgs(key=key))
            dispatch_result = await dispatch_action(dom_result[2], action_obj)
            print("[executor - press_key result]: ", dispatch_result)

        # Execution of the wait handler
        elif llm_action.action == "wait": 
            # Use LLM's seconds if provided, otherwise default to 5.0
            seconds = llm_action.args.seconds or 5.0
            actual_action = "wait"
            actual_args = {"seconds": seconds}

            # run wait action
            dom_result = await dom_extractor.main(page)
            action_obj = Action(action="wait", args=ActionArgs(seconds=seconds))
            dispatch_result = await dispatch_action(dom_result[2], action_obj)
            print("[executor - wait result]: ", dispatch_result)

        # Build execution log from ACTUAL dispatch result (not LLM prediction)
        if dispatch_result:
            args_str = ', '.join(f"{k}={v}" for k, v in actual_args.items()) or 'None'
            execution_log = (
                f"[Executor] Action: {dispatch_result.action}\n"
                f"[Executor] Args: {args_str}\n"
                f"[Executor] Status: {dispatch_result.status}\n"
                f"[Executor] Message: {dispatch_result.message}"
            )
            if dispatch_result.status == "failure":
                execution_log += f"\n[Executor] Error Type: {dispatch_result.error_type}"
        else:
            # Fallback if no dispatch happened (unknown action)
            execution_log = (
                f"[Executor] Action: {llm_action.action}\n"
                f"[Executor] Args: None\n"
                f"[Executor] Status: failure\n"
                f"[Executor] Message: Unknown or unsupported action type"
            )
        
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

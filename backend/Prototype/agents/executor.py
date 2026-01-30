"""
Execution Agent
Translates high-level plan steps into specific browser actions.
"""

from langchain_core.messages import SystemMessage, HumanMessage
from schema import ExecutionResult
from state import ProjectState
from models import Models
from prompt_loader import get_execution_prompt
# import DOMExtractionUnderstanding


class Executor:
    """
    LLM-powered Executor that translates plan steps into browser actions.
    Uses the execution prompt from the prompts directory.
    """
    
    def __init__(self):
        self.llm = Models.executor(ExecutionResult)
        # Load the execution prompt from the prompts directory
        self.system_prompt = get_execution_prompt()

    def __call__(self, state: ProjectState) -> dict:
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
        
        # Simulate URL change for navigation actions
        new_url = current_url
        if action.action == "navigate" and action.args.url:
            new_url = action.args.url
        elif action.action == "click" and "login" in current_task.lower():
            if "my.ucf" in current_url:
                new_url = "https://my.ucf.edu/dashboard"
        
        return {
            "number_of_transactions": state.get("number_of_transactions", 0) + 1,
            "reasoning_log": [execution_log],
            "current_url": new_url,
        }
    
    def _get_user_intent(self, state: ProjectState) -> str:
        """Extract user intent from messages."""
        user_message = state["messages"][0] if state["messages"] else None
        if isinstance(user_message, dict):
            return user_message.get("content", "Unknown intent")
        elif hasattr(user_message, "content"):
            return user_message.content
        return str(user_message) if user_message else "Unknown intent"
    
    def _get_simulated_dom(self, url: str, task: str) -> str:
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

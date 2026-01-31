"""
Verification Agent
Evaluates whether execution actions satisfied the plan step.
"""

from langchain_core.messages import SystemMessage, HumanMessage
from schema import VerificationResult
from state import ProjectState
from models import Models
from prompt_loader import get_verification_prompt


class Verifier:
    """
    LLM-powered Verifier that checks if actions succeeded.
    Uses the verification prompt from the prompts directory.
    """
    
    # Track attempts to occasionally simulate failures
    _attempt_count = 0
    
    def __init__(self):
        self.llm = Models.verifier(VerificationResult)
        # Load the verification prompt from the prompts directory
        self.system_prompt = get_verification_prompt()

    def __call__(self, state: ProjectState) -> dict:
        Verifier._attempt_count += 1
        
        current_task = state.get("current_task", "Unknown task")
        current_plan = state.get("current_plan", [])
        current_step = state.get("current_step_index", 0)
        reasoning_log = state.get("reasoning_log", [])
        last_execution = reasoning_log[-1] if reasoning_log else "No execution log"
        user_intent = self._get_user_intent(state)
        
        # Get simulated states
        before_url = state.get("previous_url", state.get("current_url", "unknown"))
        after_url = state.get("current_url", "unknown")
        simulated_result = self._get_simulated_result(current_task, Verifier._attempt_count)
        
        # Determine if this is the last step
        is_last_step = current_step >= len(current_plan) - 1 if current_plan else False
        
        # Build context following the prompt's expected inputs
        context = f"""
        MAIN_GOAL: {user_intent}

        PLAN_STEP: {current_task}

        EXECUTION_OUTPUT:
        {last_execution}

        BEFORE_STATE:
        URL: {before_url}

        AFTER_STATE:
        URL: {after_url}
        {simulated_result}

        IS_FINAL_STEP: {is_last_step}

        Verify if the action was successful based on this information.
        """

        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=context)
        ]

        result: VerificationResult = self.llm.invoke(messages)
        
        verification_log = (
            f"[Verifier] Verdict: {result.verdict}\n"
            f"[Verifier] Step Complete: {result.step_complete}\n"
            f"[Verifier] Goal Complete: {result.goal_complete}\n"
            f"[Verifier] Message: {result.message}\n"
            f"[Verifier] Handoff: {result.handoff}"
        )
        
        if result.error_type != "none":
            verification_log += f"\n[Verifier] Error Type: {result.error_type}"
        
        return {
            "number_of_transactions": state.get("number_of_transactions", 0) + 1,
            "needs_fallback": result.handoff == "fallback",
            "is_complete": result.goal_complete,
            "reasoning_log": [verification_log],
        }
    
    def _get_user_intent(self, state: ProjectState) -> str:
        """Extract user intent from messages."""
        user_message = state["messages"][0] if state["messages"] else None
        if isinstance(user_message, dict):
            return user_message.get("content", "Unknown intent")
        elif hasattr(user_message, "content"):
            return user_message.content
        return str(user_message) if user_message else "Unknown intent"
    
    def _get_simulated_result(self, task: str, attempt: int) -> str:
        """Generate simulated post-action page state."""
        
        # Occasionally simulate a failure (roughly 15% chance on early attempts)
        if attempt <= 2 and attempt % 6 == 0:
            return (
                "DOM_SNAPSHOT:\n"
                "[role='dialog'] 'Cookie Consent'\n"
                "  [role='button'] 'Accept All'\n"
                "  [role='button'] 'Reject All'\n"
                "\nNote: An overlay modal appeared blocking the target element."
            )
        
        if "click" in task.lower() and "login" in task.lower():
            return (
                "DOM_SNAPSHOT:\n"
                "[role='main']\n"
                "  [role='heading'] 'Welcome, Student'\n"
                "  [role='link'] 'My Courses'\n"
                "  [role='link'] 'Canvas'\n"
                "  [role='link'] 'Knights Email'\n"
                "\nLogin button was clicked. Page is now showing the dashboard."
            )
        elif "username" in task.lower() or "enter" in task.lower():
            return (
                "DOM_SNAPSHOT:\n"
                "[role='textbox'] 'username' value='student@ucf.edu'\n"
                "[role='textbox'] 'password' placeholder='Enter your password'\n"
                "[role='button'] 'Sign In'\n"
                "\nText was successfully entered into the input field."
            )
        elif "navigate" in task.lower():
            return (
                "DOM_SNAPSHOT:\n"
                "[role='main']\n"
                "  [role='heading'] 'Page Title'\n"
                "  [role='navigation'] 'Main Menu'\n"
                "\nNavigation successful. New page has loaded."
            )
        else:
            return f"Action completed successfully. Page state updated as expected after: {task}"
    
    @classmethod
    def reset_simulation(cls):
        """Reset the attempt counter for new test runs."""
        cls._attempt_count = 0

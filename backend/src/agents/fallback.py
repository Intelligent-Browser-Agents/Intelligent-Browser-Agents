"""
Fallback Agent
Diagnoses failures and proposes recovery strategies.
"""

from langchain_core.messages import SystemMessage, HumanMessage
from schema import FallbackStrategy
from state import ProjectState
from models import Models
from prompt_loader import get_fallback_prompt


class Fallback:
    """
    LLM-powered Fallback agent that proposes recovery strategies.
    Uses the fallback prompt from the prompts directory.
    """
    
    def __init__(self):
        self.llm = Models.fallback(FallbackStrategy)
        # Load the fallback prompt from the prompts directory
        self.system_prompt = get_fallback_prompt()

    def __call__(self, state: ProjectState) -> dict:
        current_task = state.get("current_task", "Unknown task")
        reasoning_log = state.get("reasoning_log", [])
        user_intent = self._get_user_intent(state)
        current_url = state.get("current_url", "unknown")
        
        # Get the last verification and execution outputs
        last_verification = reasoning_log[-1] if reasoning_log else "Verification failed"
        last_execution = reasoning_log[-2] if len(reasoning_log) >= 2 else "No execution log"
        
        # Build context following the prompt's expected inputs
        context = f"""
MAIN_GOAL: {user_intent}

PLAN_STEP (failed): {current_task}

VERIFICATION_OUTPUT:
{last_verification}

EXECUTION_OUTPUT:
{last_execution}

AFTER_STATE:
URL: {current_url}
{self._get_simulated_dom(current_url)}

Analyze this failure and propose a recovery strategy.
"""

        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=context)
        ]

        strategy: FallbackStrategy = self.llm.invoke(messages)
        
        # Build fallback log
        fallback_log = (
            f"[Fallback] Update Type: {strategy.update_type}\n"
            f"[Fallback] Diagnosis: {strategy.diagnosis}\n"
            f"[Fallback] Message to Orchestration: {strategy.message_to_orchestration}"
        )
        
        if strategy.proposed_step:
            fallback_log += f"\n[Fallback] Proposed Step: {strategy.proposed_step}"
        if strategy.insert_step:
            fallback_log += f"\n[Fallback] Insert Step: {strategy.insert_step}"
        if strategy.requested_context:
            fallback_log += f"\n[Fallback] Requested Context: {', '.join(strategy.requested_context)}"
        
        # Determine the new task based on the recovery strategy
        new_task = current_task
        if strategy.update_type == "revise_step" and strategy.proposed_step:
            new_task = strategy.proposed_step
        elif strategy.update_type == "insert_step_before" and strategy.insert_step:
            new_task = strategy.insert_step
        
        return {
            "number_of_transactions": state.get("number_of_transactions", 0) + 1,
            "current_task": new_task,
            "reasoning_log": [fallback_log],
            "needs_fallback": False,
        }
    
    def _get_user_intent(self, state: ProjectState) -> str:
        """Extract user intent from messages."""
        user_message = state["messages"][0] if state["messages"] else None
        if isinstance(user_message, dict):
            return user_message.get("content", "Unknown intent")
        elif hasattr(user_message, "content"):
            return user_message.content
        return str(user_message) if user_message else "Unknown intent"
    
    def _get_simulated_dom(self, url: str) -> str:
        """Generate simulated DOM snapshot for fallback analysis."""
        return """
DOM_SNAPSHOT:
[role='dialog'] 'Cookie Consent'
  [role='button'] 'Accept All'
  [role='button'] 'Reject All'

[role='main'] (partially obscured by dialog)
  [role='textbox'] 'username'
  [role='textbox'] 'password'
  [role='button'] 'Sign In'
"""

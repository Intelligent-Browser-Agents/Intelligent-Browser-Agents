"""
Interaction Agent
Formats internal results into user-facing responses.
"""

from langchain_core.messages import SystemMessage, HumanMessage
from schema import InteractionResponse
from state import ProjectState
from models import Models
from prompt_loader import get_interaction_prompt


class InteractionAgent:
    """
    LLM-powered Interaction agent that generates user-facing responses.
    Uses the interaction prompt from the prompts directory.
    """
    
    def __init__(self):
        self.llm = Models.interaction(InteractionResponse)
        # Load the interaction prompt from the prompts directory
        self.system_prompt = get_interaction_prompt()

    def __call__(self, state: ProjectState) -> dict:
        user_intent = self._get_user_intent(state)
        plan_history = state.get("plan_history", [])
        reasoning_log = state.get("reasoning_log", [])
        current_url = state.get("current_url", "unknown")
        is_complete = state.get("is_complete", False)
        
        # Determine system status
        system_status = "goal_completed" if is_complete else "needs_clarification"
        
        # Build verified result summary from reasoning logs
        actions_summary = "\n".join([
            f"- {log[:150]}..." if len(log) > 150 else f"- {log}" 
            for log in reasoning_log[-5:]
        ])
        
        # Build context following the prompt's expected inputs
        context = f"""
MAIN_GOAL: {user_intent}

VERIFIED_RESULT:
Final URL: {current_url}
Plan Executed: {plan_history[-1] if plan_history else 'N/A'}

Recent Actions:
{actions_summary}

SYSTEM_STATUS: {system_status}

Generate a user-facing response based on this information.
"""

        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=context)
        ]

        response: InteractionResponse = self.llm.invoke(messages)
        
        # Build the final message for the user
        if response.type == "finish":
            final_message = response.message
            if response.data:
                final_message += f"\n\n{response.data}"
        else:  # request
            final_message = response.message
            if response.requested_fields:
                final_message += "\n\nPlease provide:"
                for field in response.requested_fields:
                    final_message += f"\n- {field}"
        
        interaction_log = (
            f"[Interaction] Type: {response.type}\n"
            f"[Interaction] Generated user response"
        )
        
        if response.type == "request":
            interaction_log += f"\n[Interaction] Requested {len(response.requested_fields)} fields"
        
        return {
            "number_of_transactions": state.get("number_of_transactions", 0) + 1,
            "reasoning_log": [interaction_log],
            "messages": [{"role": "assistant", "content": final_message}],
        }
    
    def _get_user_intent(self, state: ProjectState) -> str:
        """Extract user intent from messages."""
        user_message = state["messages"][0] if state["messages"] else None
        if isinstance(user_message, dict):
            return user_message.get("content", "Unknown intent")
        elif hasattr(user_message, "content"):
            return user_message.content
        return str(user_message) if user_message else "Unknown intent"

"""
Orchestration Agent
Converts user requests into ordered high-level subtasks for browser automation.
"""

from langchain_core.messages import SystemMessage, HumanMessage
from schema import OrchestratorPlan, OrchestratorDecision
from state import ProjectState
from models import Models
from prompt_loader import get_orchestration_prompt


# Decision-making prompt for step-by-step execution
DECISION_SYSTEM_PROMPT = """
You are the Decision Maker in a browser automation system.
You have an existing plan and need to decide what to do next.

Given:
- The current plan (list of steps)
- Which step we're on
- What just happened (verification result)
- The current page state

Decide:
1. plan_status: 
   - MAINTAIN: Everything is going well, continue with the plan
   - UPDATE: Something went wrong, we need to adjust the plan
   - CREATE: Major issue requires a completely new plan (rare)

2. current_step_index: Which step to execute next (0-based)

3. next_task_for_executor: The specific instruction for this step

4. is_mission_complete: True only if we've completed ALL steps successfully

IMPORTANT: Only mark complete when the FINAL step is done and verified.
"""


class Orchestrator:
    """
    LLM-powered Orchestrator that creates plans and tracks execution progress.
    
    Two modes:
    - Planning: Creates a multi-step plan when needed (uses prompt from file)
    - Decision: Decides next action based on current state
    """
    
    def __init__(self):
        self.planner = Models.planner(OrchestratorPlan)
        self.decision_maker = Models.decision_maker(OrchestratorDecision)
        # Load the orchestration prompt from the prompts directory
        self.planning_prompt = get_orchestration_prompt()

    def __call__(self, state: ProjectState) -> dict:
        # Extract user intent
        user_intent = self._get_user_intent(state)
        
        # Get current plan (if any)
        current_plan = state.get("current_plan", [])
        current_step = state.get("current_step_index", 0)
        
        # Only create a new plan if we don't have one yet
        needs_new_plan = len(current_plan) == 0
        
        # Simulate page context for testing
        simulated_page = self._get_simulated_page_context(
            state.get("current_url", ""),
            current_step,
            user_intent
        )

        if needs_new_plan:
            return self._create_plan(user_intent, simulated_page, state)
        else:
            return self._make_decision(user_intent, current_plan, current_step, simulated_page, state)

    def _create_plan(self, user_intent: str, page_state: str, state: ProjectState) -> dict:
        """Generate a new multi-step plan using the orchestration prompt."""
        
        # Build the context for the planner
        context = f"""
        USER REQUEST: {user_intent}

        CURRENT URL: {state.get('current_url', 'https://google.com')}

        PAGE STATE:
        {page_state}

        Based on this request, create a plan following the output format specified.
        """
                
        messages = [
            SystemMessage(content=self.planning_prompt),
            HumanMessage(content=context)
        ]
        
        plan: OrchestratorPlan = self.planner.invoke(messages)
        
        # Handle clarification requests
        if plan.needs_clarification:
            reasoning = f"[Planner] Needs clarification:\n"
            for q in plan.clarifying_questions:
                reasoning += f"  - {q}\n"
            
            return {
                "number_of_transactions": state.get("number_of_transactions", 0) + 1,
                "current_plan": [],
                "plan_history": [],
                "current_step_index": 0,
                "plan_status": "NEEDS_CLARIFICATION",
                "current_task": "Awaiting user clarification",
                "reasoning_log": [reasoning],
                "is_complete": False,
                "needs_fallback": False
            }
        
        # Build reasoning log
        reasoning = f"[Planner] Goal: {plan.goal}\n"
        reasoning += f"[Planner] Created plan with {len(plan.steps)} steps:\n"
        for i, step in enumerate(plan.steps):
            reasoning += f"  {i+1}. {step}\n"
        
        return {
            "number_of_transactions": state.get("number_of_transactions", 0) + 1,
            "current_plan": plan.steps,
            "plan_history": plan.steps,
            "current_step_index": 0,
            "plan_status": "MAINTAIN",
            "current_task": plan.steps[0] if plan.steps else "No steps generated",
            "reasoning_log": [reasoning],
            "is_complete": False,
            "needs_fallback": False
        }

    def _make_decision(self, user_intent: str, current_plan: list, current_step: int, 
                       page_state: str, state: ProjectState) -> dict:
        """Decide what to do next given the current plan and state."""
        
        plan_display = "\n".join([
            f"  {'→' if i == current_step else ' '} {i+1}. {step}" 
            for i, step in enumerate(current_plan)
        ])
        
        reasoning_log = state.get("reasoning_log", [])
        last_result = reasoning_log[-1] if reasoning_log else "No previous action"
        
        context = f"""
        USER GOAL: {user_intent}

        CURRENT PLAN:
        {plan_display}

        CURRENT STEP INDEX: {current_step}

        LAST ACTION RESULT:
        {last_result}

        PAGE STATE AFTER LAST ACTION:
        {page_state}

        NEEDS FALLBACK: {state.get('needs_fallback', False)}

        Based on this, decide what to do next.
        """
        
        messages = [
            SystemMessage(content=DECISION_SYSTEM_PROMPT),
            HumanMessage(content=context)
        ]
        
        decision: OrchestratorDecision = self.decision_maker.invoke(messages)
        
        reasoning = (
            f"[Decision] Status: {decision.plan_status} | "
            f"Step: {decision.current_step_index + 1}/{len(current_plan)} | "
            f"Complete: {decision.is_mission_complete}\n"
            f"[Decision] CoT: {decision.chain_of_thought[:200]}..."
        )
        
        return {
            "number_of_transactions": state.get("number_of_transactions", 0) + 1,
            "current_step_index": decision.current_step_index,
            "plan_status": decision.plan_status,
            "current_task": decision.next_task_for_executor,
            "reasoning_log": [reasoning],
            "is_complete": decision.is_mission_complete,
            "needs_fallback": False
        }

    def _get_user_intent(self, state: ProjectState) -> str:
        """Extract user intent from messages."""
        user_message = state["messages"][0] if state["messages"] else None
        if isinstance(user_message, dict):
            return user_message.get("content", "Unknown intent")
        elif hasattr(user_message, "content"):
            return user_message.content
        return str(user_message) if user_message else "Unknown intent"

    def _get_simulated_page_context(self, url: str, step: int, intent: str) -> str:
        """Generate simulated page descriptions for testing."""
        
        if "ucf" in url.lower() or "login" in intent.lower():
            stages = [
                "UCF homepage loaded. 'myUCF' login link visible in navigation. Search box and menu items present.",
                "Login page displayed. Username field (id='username'), password field (id='password'), 'Sign In' button visible.",
                "Username entered successfully. Field shows masked input. Password field ready for input.",
                "Password entered successfully. Both fields filled. 'Sign In' button ready to click.",
                "Login successful! Dashboard showing student name, course schedule, Canvas and Knights Email links."
            ]
        else:
            stages = [
                f"Page loaded at {url}. Navigation and content elements visible.",
                "Interacted with page. Elements responding to actions.",
                "Progress made. Page state updated.",
                "Near completion. Final actions pending.",
                "Task completed successfully."
            ]
        
        return stages[min(step, len(stages) - 1)]

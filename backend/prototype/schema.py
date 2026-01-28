"""
Schema definitions for all agents.
These Pydantic models define the structured output format for each agent,
aligned with the prompts in the prompts/ directory.
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Literal


# =============================================================================
# ORCHESTRATION LAYER
# Aligned with: prompts/orchestration.prompt.md
# =============================================================================

class OrchestratorPlan(BaseModel):
    """
    Schema for the Orchestration Agent's plan output.
    Converts user requests into ordered high-level subtasks.
    """
    needs_clarification: bool = Field(
        description="True if essential information is missing and clarification is needed before planning."
    )
    clarifying_questions: List[str] = Field(
        default_factory=list,
        description="1-3 targeted questions to ask if clarification is needed. Empty if needs_clarification is false."
    )
    goal: str = Field(
        description="One-sentence clarified browsing goal based on the user's request."
    )
    steps: List[str] = Field(
        default_factory=list,
        description="Ordered list of 3-8 high-level steps to achieve the goal. Empty if needs_clarification is true."
    )


# =============================================================================
# EXECUTION LAYER
# Aligned with: prompts/execution.prompt.md
# =============================================================================

class ExecutionArgs(BaseModel):
    """Arguments for browser actions."""
    url: Optional[str] = Field(default=None, description="URL for navigation actions.")
    role: Optional[str] = Field(default=None, description="ARIA role for element targeting.")
    name: Optional[str] = Field(default=None, description="Accessible name for element targeting.")
    text: Optional[str] = Field(default=None, description="Text to type or search query.")
    direction: Optional[Literal["up", "down"]] = Field(default=None, description="Scroll direction.")
    key: Optional[str] = Field(default=None, description="Key to press (e.g., 'Enter', 'Escape').")
    seconds: Optional[float] = Field(default=None, description="Duration for wait actions.")


class ExecutionResult(BaseModel):
    """
    Schema for the Execution Agent's action output.
    Translates plan steps into specific browser actions.
    """
    action: Literal["navigate", "click", "type", "search", "scroll", "press_key", "wait"] = Field(
        description="The browser action to perform."
    )
    args: ExecutionArgs = Field(
        description="Arguments for the action."
    )
    status: Literal["success", "failure"] = Field(
        description="Whether the action can be attempted or not."
    )
    error_type: Literal[
        "none", 
        "element_not_found", 
        "ambiguous_step", 
        "tool_limit", 
        "navigation_blocked", 
        "unknown"
    ] = Field(
        default="none",
        description="Type of error if status is failure."
    )
    message: str = Field(
        description="One concise sentence describing what was done or why it failed."
    )


# =============================================================================
# VERIFICATION LAYER
# Aligned with: prompts/verification.prompt.md
# =============================================================================

class VerificationResult(BaseModel):
    """
    Schema for the Verification Agent's output.
    Evaluates whether the execution satisfied the plan step.
    """
    verdict: Literal["success", "failure"] = Field(
        description="Whether the action successfully completed the step."
    )
    step_complete: bool = Field(
        description="True if the current plan step is fully satisfied."
    )
    goal_complete: bool = Field(
        description="True if the overall goal has been achieved."
    )
    error_type: Literal[
        "none",
        "execution_failure",
        "mismatch",
        "blocked",
        "insufficient_evidence",
        "unexpected_state"
    ] = Field(
        default="none",
        description="Type of error if verdict is failure."
    )
    message: str = Field(
        description="One concise sentence explaining the verdict."
    )
    handoff: Literal["orchestration", "fallback"] = Field(
        description="Which agent should handle the next step."
    )


# =============================================================================
# FALLBACK LAYER
# Aligned with: prompts/fallback.prompt.md
# =============================================================================

class FallbackStrategy(BaseModel):
    """
    Schema for the Fallback Agent's recovery output.
    Diagnoses failures and proposes revised instructions.
    """
    update_type: Literal["revise_step", "insert_step_before", "request_context", "abort"] = Field(
        description="The type of plan modification needed."
    )
    diagnosis: str = Field(
        description="One short sentence describing the failure cause."
    )
    proposed_step: Optional[str] = Field(
        default=None,
        description="A single revised high-level step if update_type is 'revise_step'."
    )
    insert_step: Optional[str] = Field(
        default=None,
        description="A prerequisite step to insert before the failed step if update_type is 'insert_step_before'."
    )
    requested_context: List[str] = Field(
        default_factory=list,
        description="Specific pieces of missing information needed if update_type is 'request_context'."
    )
    message_to_orchestration: str = Field(
        description="One concise instruction describing what to change next."
    )


# =============================================================================
# INTERACTION LAYER
# Aligned with: prompts/interaction.prompt.md
# =============================================================================

class InteractionResponse(BaseModel):
    """
    Schema for the Interaction Agent's user-facing output.
    Formats internal results into clear user responses.
    """
    type: Literal["finish", "request"] = Field(
        description="'finish' for completed tasks, 'request' for clarification needed."
    )
    message: str = Field(
        description="Clean, user-facing summary or clarification request."
    )
    data: Optional[str] = Field(
        default=None,
        description="Final result or summary data if type is 'finish'."
    )
    requested_fields: List[str] = Field(
        default_factory=list,
        description="Specific missing information needed if type is 'request'."
    )


# =============================================================================
# LEGACY SCHEMAS (kept for backwards compatibility)
# =============================================================================

class OrchestratorDecision(BaseModel):
    """
    Legacy schema for orchestrator decision-making.
    Used for step-by-step plan execution tracking.
    """
    chain_of_thought: str = Field(
        description="Analysis of current progress, what just happened, and what should happen next."
    )
    plan_status: Literal["MAINTAIN", "UPDATE", "CREATE"] = Field(
        description="MAINTAIN: continue with current plan. UPDATE: modify the plan. CREATE: make a new plan."
    )
    current_step_index: int = Field(
        description="The index (0-based) of the step we're currently on or about to execute."
    )
    next_task_for_executor: str = Field(
        description="The specific instruction for the Executor."
    )
    is_mission_complete: bool = Field(
        description="True only if ALL planned steps are done and the user's goal is achieved."
    )


class HumanInterrupt(BaseModel):
    """Schema for when the agent needs to pause and ask the user for help."""
    interrupt_type: Literal[
        "AUTH_BLOCK", 
        "CLARIFY_INTENT", 
        "TECHNICAL_RECOVERY", 
        "SAFETY_CHECK", 
        "STATUS_SYNC"
    ] = Field(description="The category of the interruption.")
    
    internal_reasoning: str = Field(description="CoT: Why are we stopping?")
    user_facing_question: str = Field(description="The elevated prose to show the user.")
    suggested_options: Optional[List[str]] = Field(
        default=None,
        description="Pre-defined buttons for the user to click."
    )


# =============================================================================
# LEGACY ALIASES (for backwards compatibility)
# =============================================================================

# These aliases allow existing code to work while transitioning to new schemas
BrowserAction = ExecutionResult  # Old name -> New name
UserResponse = InteractionResponse  # Old name -> New name

from pydantic import BaseModel, Field
from typing import List, Optional, Literal




# This is preliminary schema for the agents. We will consider a dynamic approach to loading prompts based on the website context.

# Note that all prompts are placeholders. 


# ORCHESTRATION LAYER

class OrchestratorPlan(BaseModel):
    """The schema for the primary reasoning node."""
    chain_of_thought: str = Field(
        description="Detailed analysis of the current page state, DOM elements, and progress toward the user goal."
    )
    high_level_goal: str = Field(
        description="The current objective (e.g., 'Navigate to the checkout page')."
    )
    next_task_for_executor: str = Field(
        description="Discrete instruction for Execution agent (e.g., 'Click the red button with ID cart-01')."
    )
    is_mission_complete: bool = Field(
        description="True only if the user's ultimate request is finished."
    )

# EXECUTION LAYER

class BrowserAction(BaseModel):
    """The schema to turn intent into browser commands."""
    action_type: Literal["click", "type", "scroll", "wait", "navigate"] = Field(
        description="The low-level browser operation to perform."
    )
    selector: Optional[str] = Field(
        description="The CSS or XPath selector for the element."
    )
    text_input: Optional[str] = Field(
        description="The string to type, if action is 'type'."
    )
    local_reasoning: str = Field(
        description="CoT on why this specific action implements the Orchestrator's command."
    )

# VERIFICATION LAYER

class VerificationResult(BaseModel):
    """The schema for the 'Meta' CoT checking correctness."""
    was_action_successful: bool = Field(
        description="Did the page change as expected after the execution?"
    )
    visual_confirmation: str = Field(
        description="Description of what was seen in the screenshot to verify the result."
    )
    error_detected: Optional[str] = Field(
        description="If things went wrong, describe the error (e.g., 'Overlay blocked the click')."
    )

# FALLBACK LAYER

class FallbackStrategy(BaseModel):
    """The schema for alternative reasoning when the first attempt fails."""
    failure_analysis: str = Field(
        description="CoT: Why did the previous action fail? (e.g., 'Element was obscured', 'Timeout')."
    )
    alternative_approach: str = Field(
        description="A new tactical plan (e.g., 'Try scrolling first' or 'Use XPath instead of CSS selector')."
    )
    retry_instruction: str = Field(
        description="The specific directive to attempt next."
    )

# INTERACTION LAYER

class UserResponse(BaseModel):
    """The final, user-facing response schema."""
    final_answer: str = Field(
        description="The elevated prose response to the user. No internal technical jargon."
    )
    summary_of_actions: Optional[str] = Field(
        description="A brief, high-level list of what was done (e.g., 'I successfully booked your flight')."
    )
    suggested_next_steps: List[str] = Field(
        default_factory=list,
        description="Any further actions the user might want to take."
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
    suggested_options: Optional[list[str]] = Field(description="Pre-defined buttons for the user to click.")
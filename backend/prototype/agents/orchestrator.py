import os
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
from schema import OrchestratorPlan # Importing the contract we built
from state import ProjectState

class Orchestrator:
    def __init__(self, model_name="gemini-3.0-ultra"):
        self.llm = ChatGoogleGenerativeAI(
            model=model_name,
            temperature=0.2
        ).with_structured_output(OrchestratorPlan)

    def __call__(self, state: ProjectState):
        # Grab the latest plan
        last_plan = state["plan_history"][-1] if state["plan_history"] else "No previous plan."
        
        # Build the text-based context
        context_text = (
            f"User Intent: {state['messages'][0].content}\n"
            f"Current URL: {state['current_url']}\n"
            f"Previous Plan: {last_plan}\n"
            f"Last Action Attempted: {state.get('current_task', 'None')}"
        )

        # Create the message content list
        # We start with the text context
        content = [{"type": "text", "text": context_text}]

        # Optional Screenshot: Only add if it exists in the state
        if state.get("screenshot"):
            content.append({
                "type": "image_url", 
                "image_url": f"data:image/png;base64,{state['screenshot']}"
            })

        # Execute the CoT Reasoning
        messages = [
            SystemMessage(content="Analyze the state vs. the plan. If the last action failed, revise the plan."),
            HumanMessage(content=content)
        ]

        prediction = self.llm.invoke(messages)

        return {
            "plan_history": prediction.planned_steps,
            "reasoning_log": [prediction.chain_of_thought],
            "current_task": prediction.next_task_for_executor,
            "is_complete": prediction.is_complete
        }
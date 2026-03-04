"""
Fallback Verification Agent

- Verifies model confidence
- Uses Gemini to generate clarification questions when confidence is low
- Raises ClarificationRequired to halt orchestration until user responds
"""

import os
import google.generativeai as genai



# Gemini Configuration


genai.configure(api_key=os.environ["GEMINI_API_KEY"])

# Use fast + inexpensive model for clarification
model = genai.GenerativeModel("gemini-2.5-flash")



# Custom Exception


class ClarificationRequired(Exception):
    """
    Raised when confidence is below threshold and user clarification is required.
    """

    def __init__(self, question: str):
        self.question = question
        super().__init__(question)



# AI Question Generator


def generate_clarification_question(problem: str) -> str:

    prompt = f"""
    You are an AI assistant helping clarify user issues in a web application.

    Rewrite the following predicted issue as a single, polite clarification question.
    Keep it conversational.
    Do not include explanations.
    Only return the question.

    Predicted issue:
    {problem}
    """

    try:
        response = model.generate_content(prompt)
        return response.text.strip()

    except Exception:
        # Fallback in case Gemini fails
        return (
            f"I may have misunderstood. Are you experiencing this issue: "
            f"'{problem}'? If not, could you describe the correct issue?"
        )



# Fallback Verification Agent
def fallback_verification_agent(
    confidence_score: float,
    problem: str,
    solution: str,
    user_response: str | None = None
) -> tuple[bool, str, str]:
    """
    Verifies whether a response meets the confidence threshold.

    Returns:
        (True, "", "") if confidence_score >= 0.9
        Raises ClarificationRequired if clarification needed
        (False, user_response, "") once clarification received
    """

    THRESHOLD = 0.9

    # High confidence → proceed normally
    if confidence_score >= THRESHOLD:
        return True, "", ""

    # Low confidence & no user clarification yet → halt execution
    if user_response is None:
        question = generate_clarification_question(problem)
        raise ClarificationRequired(question)

    # User has clarified → continue pipeline using their response
    return False, user_response, ""

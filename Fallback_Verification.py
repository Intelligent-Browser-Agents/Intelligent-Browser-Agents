def fallback_verification_agent(confidence_score: float,problem: str,solution: str) -> tuple[bool, str, str]:
    """
    Verifies whether a response meets the confidence threshold.

    Parameters:
        confidence_score (float): Confidence score between 0 and 1
        problem (str): Reason confidence is low
        solution (str): Suggested fix for the issue

    Returns:
        (bool, str, str):
            - True, "", "" if confidence_score >= 0.9
            - False, problem, solution if confidence_score < 0.9
    """

    if confidence_score >= 0.9:
        return True, "", ""

    return False, problem, solution

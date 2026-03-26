import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = BACKEND_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from agents.orchestrator import Orchestrator
from agents.verifier import Verifier
from agents.executor import Executor


def test_verifier_marks_success_and_resets_attempts():
    verifier = Verifier()
    state = {
        "current_step_index": 0,
        "current_plan": ["Navigate to https://ucf.edu"],
        "reasoning_log": [
            "[Executor] Action: navigate\n"
            "[Executor] Args: url=https://ucf.edu\n"
            "[Executor] Status: success\n"
            "[Executor] Message: Navigated to https://ucf.edu"
        ],
        "step_attempts": 3,
        "number_of_transactions": 1,
    }

    result = verifier(state)

    assert result["needs_fallback"] is False
    assert result["is_complete"] is True
    assert result["last_step_complete"] is True
    assert result["step_attempts"] == 0


def test_verifier_marks_failure_and_increments_attempts():
    verifier = Verifier()
    state = {
        "current_step_index": 0,
        "current_plan": ["Enter academics in search bar"],
        "reasoning_log": [
            "[Executor] Action: search\n"
            "[Executor] Args: None\n"
            "[Executor] Status: failure\n"
            "[Executor] Message: Search action requires non-empty 'text'."
        ],
        "step_attempts": 2,
        "number_of_transactions": 4,
    }

    result = verifier(state)

    assert result["needs_fallback"] is True
    assert result["is_complete"] is False
    assert result["last_step_complete"] is False
    assert result["step_attempts"] == 3


def test_orchestrator_abort_guard_triggers():
    orchestrator = Orchestrator.__new__(Orchestrator)
    state = {
        "step_attempts": 6,
        "max_step_attempts": 6,
        "max_transactions": 80,
        "number_of_transactions": 10,
    }
    reason = orchestrator._get_abort_reason(state)
    assert "Aborted after 6 failed attempts" in reason


def test_orchestrator_advances_on_success():
    orchestrator = Orchestrator.__new__(Orchestrator)
    state = {
        "last_step_complete": True,
        "number_of_transactions": 2,
        "current_task": "Navigate to https://ucf.edu",
    }
    plan = [
        "Navigate to https://ucf.edu",
        "Enter 'academics' in the search bar.",
        "Initiate the search.",
    ]

    result = orchestrator._make_decision(plan, 0, state)

    assert result["current_step_index"] == 1
    assert result["current_task"] == "Enter 'academics' in the search bar."
    assert result["is_complete"] is False


def test_executor_anti_bot_ignores_oauth_pkce_challenge_params():
    executor = Executor.__new__(Executor)
    microsoft_oauth_url = (
        "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
        "?client_id=9199bf20-a13f-4107-85dc-02114787ef48"
        "&response_type=code"
        "&code_challenge=RW33g1c-1VXFHzui_agDyC7evuVLuNBHYLFq8q44Y8M"
        "&code_challenge_method=S256"
    )

    assert executor._is_anti_bot_page(microsoft_oauth_url) is False


def test_executor_anti_bot_detects_google_sorry_page():
    executor = Executor.__new__(Executor)
    google_sorry_url = "https://www.google.com/sorry/index?continue=https://www.google.com/search%3Fq%3Ducf"

    assert executor._is_anti_bot_page(google_sorry_url) is True

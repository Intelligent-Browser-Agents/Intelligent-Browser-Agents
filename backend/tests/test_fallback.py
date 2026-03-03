import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = BACKEND_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from agents.fallback import Fallback


def test_fallback_rewrites_missing_search_text():
    fallback = Fallback()
    state = {
        "messages": [{"role": "user", "content": "USER REQUEST: search for 'academics' on ucf"}],
        "current_task": "Initiate the search.",
        "reasoning_log": [
            "[Executor] Action: search\n"
            "[Executor] Args: None\n"
            "[Executor] Status: failure\n"
            "[Executor] Message: Search action requires non-empty 'text'.",
            "[Verifier] Verdict: failure",
        ],
        "number_of_transactions": 5,
    }
    result = fallback(state)
    assert "academics" in result["current_task"].lower()
    assert "search box" in result["current_task"].lower()


def test_fallback_rewrites_missing_click_target():
    fallback = Fallback()
    state = {
        "messages": [{"role": "user", "content": "USER REQUEST: search academics on ucf"}],
        "current_task": "Locate the search bar on the UCF website.",
        "reasoning_log": [
            "[Executor] Action: click\n"
            "[Executor] Args: None\n"
            "[Executor] Status: failure\n"
            "[Executor] Message: Click action requires at least one target field: 'role' or 'name'.",
            "[Verifier] Verdict: failure",
        ],
        "number_of_transactions": 8,
    }
    result = fallback(state)
    assert "search ucf" in result["current_task"].lower()

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
    original_task = state["current_task"]
    result = fallback(state)
    task_lower = result["current_task"].lower()
    assert result["current_task"] != original_task
    assert any(signal in task_lower for signal in ("academics", "search", "text"))


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
    original_task = state["current_task"]
    result = fallback(state)
    task_lower = result["current_task"].lower()
    assert result["current_task"] != original_task
    assert any(signal in task_lower for signal in ("search", "academics", "click", "find"))


def test_detect_repeat_loop_uses_executor_signature_and_dom_stability():
    loop = Fallback._detect_repeat_loop(
        reasoning_log=[
            "[Executor] Action: click\n"
            "[Executor] Args: role=button, name=To\n"
            "[Executor] Status: success\n"
            "[Executor] Message: Clicked button 'To'",
            "[Executor] Action: click\n"
            "[Executor] Args: role=button, name=To\n"
            "[Executor] Status: success\n"
            "[Executor] Message: Clicked button 'To'",
        ],
        last_dom_snapshot="Compose panel with To Subject Body",
        previous_dom_snapshot="Compose panel with To Subject Body",
    )

    assert loop["is_loop"] is True
    assert loop["action"] == "click"
    assert loop["repeat_count"] == 2


def test_enforce_directional_recovery_adds_recovery_hint_for_loop():
    revised, note = Fallback._enforce_directional_recovery(
        objective_task="Address the email to inesculent@gmail.com.",
        revised_task="Address the email to inesculent@gmail.com.",
        update_type="revise_step",
        loop_signal={
            "is_loop": True,
            "action": "click",
            "args": "role=button, name=To",
            "repeat_count": 2,
            "dom_unchanged": True,
        },
    )

    assert "[recovery hint:" in revised.lower()
    assert "avoid repeating the same click target" in revised.lower()
    assert "forcing a different tactical direction" in note.lower()


def test_detect_blocking_popup_identifies_booking_style_modal():
    signal = Fallback._detect_blocking_popup(
        objective_task="Search for hotels in Lisbon.",
        user_intent="Find me a hotel in Lisbon.",
        last_dom_snapshot="Genius Sign in, save money Sign in or register",
        previous_dom_snapshot="Booking homepage",
        reasoning_log=[],
    )

    assert signal["is_blocking"] is True
    assert signal["reason"] == "marketing_auth_modal_detected"


def test_detect_blocking_popup_ignores_auth_objective():
    signal = Fallback._detect_blocking_popup(
        objective_task="Sign in to Booking.com",
        user_intent="Log in to my Booking account",
        last_dom_snapshot="Genius Sign in, save money Sign in or register",
        previous_dom_snapshot="Booking homepage",
        reasoning_log=[],
    )

    assert signal["is_blocking"] is False


def test_fallback_short_circuits_to_popup_recovery_without_llm():
    class _NeverInvoke:
        def invoke(self, _messages):
            raise AssertionError("LLM should not be invoked for deterministic popup recovery")

    fallback = Fallback.__new__(Fallback)
    fallback.llm = _NeverInvoke()
    fallback.prompt = "unused"

    state = {
        "messages": [{"role": "user", "content": "USER REQUEST: find hotels in Lisbon"}],
        "current_task": "Search for hotels in Lisbon.",
        "reasoning_log": [
            "[Executor] Action: click\n"
            "[Executor] Args: role=button, name=Search\n"
            "[Executor] Status: success\n"
            "[Executor] Message: Clicked Search"
        ],
        "dom_cache": [
            "Booking.com home page",
            "Genius Sign in, save money. Sign in or register",
        ],
        "number_of_transactions": 10,
        "current_url": "https://booking.com",
    }

    result = fallback(state)

    assert "[recovery hint:" in result["current_task"].lower()
    assert "close" in result["current_task"].lower() or "dismiss" in result["current_task"].lower()
    assert "popup signal" in result["reasoning_log"][0].lower()


def test_select_last_resort_screenshot_escalates_on_repeat_loop():
    screenshot, reasons = Fallback._select_last_resort_screenshot(
        state={
            "screenshot": "data:image/jpeg;base64,ZmFrZQ==",
            "screenshot_meta": {"transaction_index": 9, "step_index": 2},
            "number_of_transactions": 10,
            "current_step_index": 2,
            "step_attempts": 2,
            "stall_cycles": 1,
        },
        loop_signal={"is_loop": True, "dom_unchanged": True},
        last_verification="[Verifier] Verdict: failure\n[Verifier] Error Type: insufficient_evidence",
        last_dom_snapshot="[role=button]",
    )

    assert screenshot.startswith("data:image/jpeg;base64,")
    assert "repeat_loop" in reasons
    assert "high_step_attempts" in reasons


def test_select_last_resort_screenshot_rejects_stale_capture():
    screenshot, reasons = Fallback._select_last_resort_screenshot(
        state={
            "screenshot": "data:image/jpeg;base64,ZmFrZQ==",
            "screenshot_meta": {"transaction_index": 1, "step_index": 2},
            "number_of_transactions": 12,
            "current_step_index": 2,
            "step_attempts": 4,
            "stall_cycles": 3,
        },
        loop_signal={"is_loop": True, "dom_unchanged": True},
        last_verification="[Verifier] Verdict: failure",
        last_dom_snapshot="",
    )

    assert screenshot == ""
    assert reasons == []

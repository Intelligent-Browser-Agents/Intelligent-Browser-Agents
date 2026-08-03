from agents.fallback import Fallback
from schema import FallbackStrategy


def test_fallback_revises_step_in_place_on_execution_failure():
    """Recoveries mutate current_plan for real now: revise_step replaces the
    failed step in the plan array (rather than decorating current_task with a
    `[Recovery Hint: ...]` marker while the plan stayed frozen), so the
    orchestrator's ordinary advance logic carries the run forward."""
    fallback = Fallback()
    state = {
        "messages": [{"role": "user", "content": "search for 'academics' on ucf"}],
        "current_plan": ["Initiate the search."],
        "current_step_index": 0,
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

    assert result["current_task"] == "stubbed revised step"
    assert result["current_plan"] == ["stubbed revised step"]
    assert result["plan_status"] == "UPDATE"
    assert result["recovery_context"]["base_task"] == "Initiate the search."


def test_fallback_revises_click_target_in_place_on_execution_failure():
    fallback = Fallback()
    state = {
        "messages": [{"role": "user", "content": "search academics on ucf"}],
        "current_plan": ["Locate the search bar on the UCF website."],
        "current_step_index": 0,
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

    assert result["current_task"] == "stubbed revised step"
    assert result["current_plan"] == ["stubbed revised step"]
    assert result["plan_status"] == "UPDATE"


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


def test_fallback_steers_away_from_a_no_op_revision_during_a_detected_loop():
    """When the model proposes revise_step but the proposed text is just the
    objective restated (a no-op) while the executor is visibly looping on one
    action, the loop-steering logic forces a different tactical direction
    instead of writing the same step back into the plan unchanged."""

    class _NoOpRevision:
        def invoke(self, _messages):
            return FallbackStrategy(
                update_type="revise_step",
                diagnosis="stubbed diagnosis",
                proposed_step="Address the email to inesculent@gmail.com.",
                insert_step=None,
                requested_context=[],
                message_to_orchestration="stubbed instruction",
            )

    fallback = Fallback.__new__(Fallback)
    fallback.llm = _NoOpRevision()
    fallback.prompt = "unused"

    repeated_click = (
        "[Executor] Action: click\n"
        "[Executor] Args: role=button, name=To\n"
        "[Executor] Status: success\n"
        "[Executor] Message: Clicked button 'To'"
    )
    state = {
        "messages": [{"role": "user", "content": "email inesculent@gmail.com"}],
        "current_plan": ["Address the email to inesculent@gmail.com."],
        "current_step_index": 0,
        "current_task": "Address the email to inesculent@gmail.com.",
        "reasoning_log": [repeated_click, repeated_click, repeated_click],
        "dom_cache": ["Compose panel with To Subject Body", "Compose panel with To Subject Body"],
        "number_of_transactions": 12,
    }

    result = fallback(state)

    assert result["current_task"] != "Address the email to inesculent@gmail.com."
    assert "avoid repeating the same click target" in result["current_task"].lower()
    assert "objective steering" in result["reasoning_log"][0].lower()
    assert result["plan_status"] == "UPDATE"


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
    """Popup recovery inserts a real prerequisite step (dismiss the popup)
    ahead of the objective in current_plan, rather than decorating current_task
    with a bracket marker while the plan stayed frozen."""
    class _NeverInvoke:
        def invoke(self, _messages):
            raise AssertionError("LLM should not be invoked for deterministic popup recovery")

    fallback = Fallback.__new__(Fallback)
    fallback.llm = _NeverInvoke()
    fallback.prompt = "unused"

    state = {
        "messages": [{"role": "user", "content": "find hotels in Lisbon"}],
        "current_plan": ["Search for hotels in Lisbon."],
        "current_step_index": 0,
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

    assert "close" in result["current_task"].lower() or "dismiss" in result["current_task"].lower()
    assert "[recovery hint:" not in result["current_task"].lower()
    assert result["current_plan"][0] == result["current_task"]
    assert result["current_plan"][1] == "Search for hotels in Lisbon."
    assert result["plan_status"] == "UPDATE"
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

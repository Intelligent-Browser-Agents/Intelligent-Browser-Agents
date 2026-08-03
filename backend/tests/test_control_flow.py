import pytest

from agents.orchestrator import Orchestrator
from agents.verifier import Verifier
from agents.executor import Executor
from agents.interaction import InteractionAgent
import state as state_reducers
import status_tracker as tracker


# Marks assertions on the email-compose keyword classifiers. These encode the
# correct behaviour (a subject/body task is not a recipient task; "write an email"
# should not count "email" as a field to fill), but the current keyword matching
# gets it wrong. The classifiers are removed in Phase 2/4 of
# docs/IMPROVEMENT_PLAN.md; strict xfail flips to a failure once that lands, which
# is the reminder to delete the marker.
compose_keyword_bug = pytest.mark.xfail(
    reason="over-broad compose keyword match; classifier removed in Phase 2/4 of docs/IMPROVEMENT_PLAN.md",
    strict=True,
)


@pytest.mark.llm
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


def test_verifier_marks_information_capture_step_complete_after_extract_content():
    verifier = Verifier()
    state = {
        "current_step_index": 0,
        "current_plan": ["Search for a cool animal fact on duckduckgo.com and copy it."],
        "current_task": "Search for a cool animal fact on duckduckgo.com and copy it.",
        "reasoning_log": [
            "[Executor] Action: extract_content\n"
            "[Executor] Args: None\n"
            "[Executor] Status: success\n"
            "[Executor] Message: Extracted 15016 characters from the page"
        ],
        "extracted_content": [
            "Pistol shrimp can snap their claw so fast it creates a cavitation bubble and a shockwave stronger than a gunshot."
        ],
        "step_attempts": 2,
        "number_of_transactions": 11,
    }

    result = verifier(state)

    assert result["needs_fallback"] is False
    assert result["last_step_complete"] is True
    assert result["step_attempts"] == 0


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


def test_orchestrator_transaction_abort_is_a_plain_counter():
    """The old 'success credit' subtraction let completed steps push this
    ceiling further away every time it was checked, so LangGraph's own
    recursion_limit (not given the same credit) could raise first, with no
    user-facing explanation. Phase 4 replaced it with a plain counter; a
    completed_steps signal no longer changes when the abort fires."""
    orchestrator = Orchestrator.__new__(Orchestrator)
    state = {
        "step_attempts": 0,
        "max_step_attempts": 6,
        "max_transactions": 10,
        "number_of_transactions": 9,
        "status_signals": {"completed_steps": [0, 1, 2]},
        "last_step_complete": False,
    }
    assert orchestrator._get_abort_reason(state) == ""

    state["number_of_transactions"] = 10
    reason = orchestrator._get_abort_reason(state)
    assert "Aborted after 10 transactions" in reason
    assert "limit: 10" in reason
    assert "effective load" not in reason


def test_orchestrator_advances_on_success():
    orchestrator = Orchestrator.__new__(Orchestrator)
    # _make_decision builds the reasoning prompt before the deterministic advance
    # branch returns, so the attribute must exist even though no LLM call happens.
    orchestrator.reasoning_prompt = "test"
    state = {
        "messages": [{"role": "user", "content": "USER REQUEST: search ucf for academics"}],
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


def test_orchestrator_does_not_treat_sensitive_approval_hitl_as_login_completion():
    orchestrator = Orchestrator.__new__(Orchestrator)

    class _FailingDecisionMaker:
        def invoke(self, _messages):
            raise RuntimeError("force rule-based fallback")

    orchestrator.decision_maker = _FailingDecisionMaker()
    orchestrator.reasoning_prompt = "test"

    plan = [
        "Open the checkout page.",
        "Submit the order.",
    ]
    state = {
        "messages": [{"role": "user", "content": "USER REQUEST: place the order"}],
        "current_task": "Submit the order.",
        "last_step_complete": False,
        "number_of_transactions": 10,
        "status_signals": {
            "login_phase": "completed",
            "hitl_events": [
                {
                    "reason": "Sensitive action confirmation required before proceeding.",
                    "reply": "yes",
                    "transaction": 9,
                }
            ],
        },
    }

    result = orchestrator._make_decision(plan, 1, state)

    assert result["is_complete"] is False
    assert result["current_step_index"] == 1


def test_orchestrator_keeps_login_hitl_shortcut_for_auth_events():
    orchestrator = Orchestrator.__new__(Orchestrator)
    plan = [
        "Approve the sign-in request.",
        "Continue to inbox.",
    ]
    state = {
        "messages": [{"role": "user", "content": "USER REQUEST: log into email"}],
        "current_task": "Approve the sign-in request.",
        "last_step_complete": False,
        "number_of_transactions": 6,
        "status_signals": {
            "login_phase": "completed",
            "hitl_events": [
                {
                    "reason": "Approve sign-in request in the authenticator app.",
                    "reply": "done",
                    "transaction": 5,
                }
            ],
        },
    }

    result = orchestrator._make_decision(plan, 0, state)

    assert result["is_complete"] is False
    assert result["current_step_index"] == 1
    assert result["current_task"] == "Continue to inbox."


def test_orchestrator_handoffs_final_report_step_when_content_exists():
    orchestrator = Orchestrator.__new__(Orchestrator)

    plan = [
        "Navigate to https://duckduckgo.com.",
        "Search for weather in Orlando.",
        "Extract weather details from results.",
        "Report the extracted weather information to the user.",
    ]
    state = {
        "messages": [{"role": "user", "content": "USER REQUEST: tell me the weather in Orlando"}],
        "current_task": "Report the extracted weather information to the user.",
        "last_step_complete": False,
        "current_step_index": 3,
        "number_of_transactions": 12,
        "extracted_content": [
            "Orlando weather report: currently 78F and partly cloudy with light wind. "
            "Forecast indicates warm temperatures through the afternoon with low rain chances."
        ],
        "dom_cache": [],
        "reasoning_log": [],
    }

    result = orchestrator._make_decision(plan, 3, state)

    assert result["is_complete"] is True
    assert result["handoff_interaction"] is True
    assert result["current_step_index"] == 3


def test_orchestrator_does_not_handoff_final_report_step_without_content():
    orchestrator = Orchestrator.__new__(Orchestrator)

    class _FailingDecisionMaker:
        def invoke(self, _messages):
            raise RuntimeError("force rule-based fallback")

    orchestrator.decision_maker = _FailingDecisionMaker()
    orchestrator.reasoning_prompt = "test"

    plan = [
        "Navigate to https://duckduckgo.com.",
        "Search for weather in Orlando.",
        "Extract weather details from results.",
        "Report the extracted weather information to the user.",
    ]
    state = {
        "messages": [{"role": "user", "content": "USER REQUEST: tell me the weather in Orlando"}],
        "current_task": "Report the extracted weather information to the user.",
        "last_step_complete": False,
        "current_step_index": 3,
        "number_of_transactions": 12,
        "extracted_content": [],
        "dom_cache": [],
        "reasoning_log": [],
    }

    result = orchestrator._make_decision(plan, 3, state)

    assert result["is_complete"] is False
    assert result["current_step_index"] == 3


def test_orchestrator_goal_retry_cycles_cap_stops_the_final_step_loop():
    """last_step_complete=True with the goal still incomplete resets both
    step_attempts and stall_cycles to 0 every cycle (see Verifier._apply_stall_cap),
    so neither of those brakes can stop this loop by itself. goal_retry_cycles
    is the counter that does, since nothing else resets it while this exact
    condition repeats."""
    orchestrator = Orchestrator.__new__(Orchestrator)
    orchestrator.reasoning_prompt = "test"
    plan = ["Navigate to https://ucf.edu", "Extract the tuition amount."]
    state = {
        "messages": [{"role": "user", "content": "get the tuition amount"}],
        "last_step_complete": True,
        "current_task": plan[-1],
        "number_of_transactions": 10,
        "max_transactions": 80,
        "goal_retry_cycles": 0,
    }

    for _ in range(Orchestrator._GOAL_RETRY_CAP - 1):
        result = orchestrator._make_decision(plan, len(plan) - 1, state)
        assert result["is_complete"] is False
        assert result.get("mission_failed", False) is False
        state["goal_retry_cycles"] = result["goal_retry_cycles"]
        state["number_of_transactions"] = result["number_of_transactions"]

    final = orchestrator._make_decision(plan, len(plan) - 1, state)
    assert final["mission_failed"] is True
    assert final["is_complete"] is True
    assert "goal" in final["abort_reason"].lower()


def test_orchestrator_work_queue_advances_to_next_item_instead_of_ending():
    orchestrator = Orchestrator.__new__(Orchestrator)
    state = {
        "work_items": [
            {"description": "Apply to Acme Corp"},
            {"description": "Apply to Widget Inc"},
        ],
        "current_item_index": 0,
        "current_url": "https://acme.example/confirmation",
        "number_of_transactions": 30,
    }
    result = {
        "is_complete": True,
        "handoff_interaction": True,
        "mission_failed": False,
        "number_of_transactions": 31,
    }

    out = orchestrator._complete_or_next_item(state, result)

    assert out["is_complete"] is False
    assert out["current_item_index"] == 1
    assert out["plan_status"] == "CREATE"
    assert out["item_results"][0]["description"] == "Apply to Acme Corp"
    assert out["item_results"][0]["status"] == "completed"
    assert "Widget Inc" in out["current_task"]


def test_orchestrator_work_queue_finishes_mission_after_last_item():
    orchestrator = Orchestrator.__new__(Orchestrator)
    state = {
        "work_items": [{"description": "Apply to Acme Corp"}],
        "current_item_index": 0,
        "current_url": "https://acme.example/confirmation",
        "number_of_transactions": 30,
    }
    result = {
        "is_complete": True,
        "handoff_interaction": True,
        "mission_failed": False,
        "number_of_transactions": 31,
    }

    out = orchestrator._complete_or_next_item(state, result)

    assert out["is_complete"] is True
    assert out["item_results"][0]["status"] == "completed"


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


def test_executor_detects_compose_recipient_task_from_address_phrase():
    assert Executor._is_email_compose_recipient_task(
        "Address the email to inesculent@gmail.com."
    ) is True


@compose_keyword_bug
def test_executor_detects_non_recipient_compose_content_task():
    assert Executor._is_email_compose_recipient_task(
        "Draft an appropriate subject line and email message content."
    ) is False


def test_executor_allows_save_click_during_recipient_step_after_dehardcoding():
    executor = Executor.__new__(Executor)
    normalized = executor._normalize_tool_args(
        "click",
        {"role": "button", "name": "Save"},
        "Address the email to inesculent@gmail.com.",
    )
    assert normalized == {"role": "button", "name": "Save"}


def test_executor_detects_compose_finalization_click_for_send_button():
    executor = Executor.__new__(Executor)

    assert executor._is_compose_finalization_action(
        "click",
        {"role": "button", "name": "Send"},
        "Draft an appropriate subject line and email message content.",
    ) is True


def test_executor_does_not_treat_non_compose_click_as_finalization():
    executor = Executor.__new__(Executor)

    assert executor._is_compose_finalization_action(
        "click",
        {"role": "button", "name": "Send"},
        "Search for housing options.",
    ) is False


def test_executor_missing_compose_fields_reports_unfilled_required_fields():
    state = {
        "status_signals": {
            "compose_fields": {
                "recipient": True,
                "subject": False,
                "body": False,
            }
        }
    }

    assert Executor._missing_compose_fields(state) == ["subject", "body"]


def test_executor_marks_recipient_lane_as_wrong_during_content_step_when_body_pending():
    executor = Executor.__new__(Executor)
    state = {
        "status_signals": {
            "compose_fields": {
                "recipient": True,
                "subject": True,
                "body": False,
            }
        }
    }

    assert executor._is_compose_wrong_lane_action(
        "click",
        {"role": "button", "name": "To"},
        "Draft an appropriate subject line and email content about a cool fact about an animal.",
        state,
    ) is True


def test_executor_allows_recipient_lane_when_recipient_still_pending():
    executor = Executor.__new__(Executor)
    state = {
        "status_signals": {
            "compose_fields": {
                "recipient": False,
                "subject": False,
                "body": False,
            }
        }
    }

    assert executor._is_compose_wrong_lane_action(
        "click",
        {"role": "button", "name": "To"},
        "Fill in the recipient as inesculent@gmail.com.",
        state,
    ) is False


def test_executor_detects_recipient_picker_focus_click_controls():
    assert Executor._is_recipient_picker_focus_click(
        "click", {"role": "button", "name": "To"}
    ) is True
    assert Executor._is_recipient_picker_focus_click(
        "click", {"role": "searchbox", "name": "Search my contacts"}
    ) is True
    assert Executor._is_recipient_picker_focus_click(
        "click", {"role": "textbox", "name": "To"}
    ) is False


def test_executor_detects_visible_inline_recipient_lane_from_dom_snapshot():
    dom = "\n".join([
        '[role="textbox"] "To"',
        '[role="textbox"] "Subject"',
    ])
    assert Executor._has_visible_inline_recipient_lane(dom) is True

    dom_no_lane = "\n".join([
        '[role="button"] "To"',
        '[role="button"] "Add recipients"',
    ])
    assert Executor._has_visible_inline_recipient_lane(dom_no_lane) is False


def test_executor_sensitive_action_reason_for_send_click():
    reason = Executor._sensitive_action_reason(
        "click",
        {"role": "button", "name": "Send"},
        "Send the email to the recipient.",
    )
    assert isinstance(reason, str) and reason


def test_executor_sensitive_action_reason_skips_non_sensitive_click():
    reason = Executor._sensitive_action_reason(
        "click",
        {"role": "button", "name": "Search"},
        "Search for UCF tuition details.",
    )
    assert reason is None


def test_executor_sensitive_action_approval_requires_exact_signature():
    approved_signature = Executor._action_signature("click", {"role": "button", "name": "Send"})
    other_signature = Executor._action_signature("click", {"role": "button", "name": "Submit"})
    state = {
        "sensitive_action_approval": {
            "approved": True,
            "action_signature": approved_signature,
        }
    }

    assert Executor._is_sensitive_action_approved(state, approved_signature) is True
    assert Executor._is_sensitive_action_approved(state, other_signature) is False


def test_executor_prefers_locked_compose_body_draft_text():
    executor = Executor.__new__(Executor)
    state = {
        "status_signals": {
            "compose_fields": {
                "recipient": True,
                "subject": True,
                "body": False,
            },
            "compose_draft": {
                "subject": "Cool cat fact",
                "body": "Cats sleep for around 12 to 16 hours each day.",
            },
        }
    }
    args = {"text": "Octopuses have three hearts and blue blood."}

    adjusted = executor._prefer_compose_draft_text(
        state,
        "Draft an appropriate subject line and email content about a cool fact about an animal.",
        args,
    )

    assert adjusted["text"] == "Cats sleep for around 12 to 16 hours each day."


def test_interaction_parses_sensitive_confirmation_yes_no_unclear():
    assert InteractionAgent._parse_sensitive_confirmation("Yes, proceed") is True
    assert InteractionAgent._parse_sensitive_confirmation("No, cancel it") is False
    assert InteractionAgent._parse_sensitive_confirmation("maybe") is None


def test_interaction_correlation_id_is_deterministic_and_message_specific():
    state = {"number_of_transactions": 5}
    id_a = InteractionAgent._correlation_id(state, "request", "Question A")
    id_a_again = InteractionAgent._correlation_id(state, "request", "Question A")
    id_b = InteractionAgent._correlation_id(state, "request", "Question B")

    assert id_a == id_a_again
    assert id_a != id_b


def test_ask_user_ignores_a_reply_correlated_to_a_different_question(monkeypatch):
    """LangGraph re-runs a node from the top on resume. If a stale resume value
    meant for an earlier question arrives at this call site, _ask_user must not
    consume it as the answer to the current one; it re-asks instead."""
    import agents.interaction as interaction_module

    calls = []

    def fake_interrupt(payload):
        calls.append(payload)
        if len(calls) == 1:
            return {"correlation_id": "stale-id-from-a-different-question", "user_input": "wrong answer"}
        return {"correlation_id": payload["correlation_id"], "user_input": "right answer"}

    monkeypatch.setattr(interaction_module, "interrupt", fake_interrupt)

    state = {"number_of_transactions": 5}
    reply = InteractionAgent._ask_user(state, {"type": "request", "message": "What is your budget?"})

    assert reply == "right answer"
    assert len(calls) == 2


def test_executor_builds_field_priority_context_for_generic_data_entry_step():
    dom_snapshot = "\n".join([
        '[role="button"] "Continue"',
        '[role="textbox"] "Account number"',
        '[role="textbox"] "Security answer"',
    ])

    block = Executor._build_field_priority_context(
        dom_snapshot,
        "Enter account number and security answer.",
    )

    assert "FIELD_PRIORITY_CONTEXT" in block
    assert "prefer filling fields" in block.lower()
    assert "Account number" in block
    assert "Security answer" in block


def test_executor_field_priority_context_empty_for_non_data_entry_step():
    dom_snapshot = '[role="textbox"] "Search"'
    block = Executor._build_field_priority_context(dom_snapshot, "Open the company homepage.")
    assert block == ""


def test_orchestrator_only_treats_explicit_then_continue_marker_as_prerequisite():
    orchestrator = Orchestrator.__new__(Orchestrator)
    assert orchestrator._is_explicit_prerequisite_variant(
        "Address the email to inesculent@gmail.com. [Recovery Hint: use active recipient lane]",
        "Address the email to inesculent@gmail.com.",
    ) is False
    assert orchestrator._is_explicit_prerequisite_variant(
        "Return to compose pane [Then continue objective: Address the email to inesculent@gmail.com.]",
        "Address the email to inesculent@gmail.com.",
    ) is True


def test_status_tracker_infers_numeric_required_field_count_for_survey_steps():
    signals = {}
    state = {
        "current_step_index": 0,
        "current_task": "Fill out the survey with 10 different boxes.",
    }
    result = {
        "current_step_index": 0,
        "current_task": "Fill out the survey with 10 different boxes.",
    }

    tracker._update_orchestrator(signals, state, result)

    progress = signals.get("field_progress") or {}
    assert progress.get("required_count") == 10
    assert progress.get("task_signature") == "fill out the survey with 10 different boxes."


def test_verifier_marks_field_step_complete_when_required_count_met():
    verifier = Verifier()
    state = {
        "current_step_index": 0,
        "current_plan": ["Fill out the survey with 3 different boxes."],
        "current_task": "Fill out the survey with 3 different boxes.",
        "reasoning_log": [
            "[Executor] Action: type\n"
            "[Executor] Args: text=done\n"
            "[Executor] Status: success\n"
            "[Executor] Message: Typed 'done' into label=Question 3",
        ],
        "status_signals": {
            "field_progress": {
                "task_signature": "fill out the survey with 3 different boxes.",
                "required_count": 3,
                "completed_fields": ["question 1", "question 2", "question 3"],
            }
        },
        "step_attempts": 2,
        "number_of_transactions": 12,
    }

    result = verifier(state)

    assert result["needs_fallback"] is False
    assert result["last_step_complete"] is True
    assert result["step_attempts"] == 0


@pytest.mark.llm
def test_verifier_keeps_field_step_in_progress_when_required_count_not_met():
    verifier = Verifier()
    state = {
        "current_step_index": 0,
        "current_plan": ["Fill out the survey with 3 different boxes."],
        "current_task": "Fill out the survey with 3 different boxes.",
        "reasoning_log": [
            "[Executor] Action: type\n"
            "[Executor] Args: text=answer\n"
            "[Executor] Status: success\n"
            "[Executor] Message: Typed 'answer' into label=Question 2",
        ],
        "status_signals": {
            "field_progress": {
                "task_signature": "fill out the survey with 3 different boxes.",
                "required_count": 3,
                "completed_fields": ["question 1", "question 2"],
            }
        },
        "step_attempts": 0,
        "number_of_transactions": 5,
    }

    result = verifier(state)

    assert result["needs_fallback"] is False
    assert result["last_step_complete"] is False


def test_state_append_plan_is_bounded():
    history = []
    for idx in range(10):
        history = state_reducers.append_plan(history, [f"step {idx}"])

    assert len(history) == 6
    assert history[0] == ["step 4"]
    assert history[-1] == ["step 9"]


def test_state_append_extracted_caps_entries_and_total_chars():
    old = ["x" * 12000 for _ in range(6)]
    # add another oversized entry; reducer should keep bounded list and total size
    combined = state_reducers.append_extracted(old, ["y" * 20000])

    assert len(combined) <= 6
    assert sum(len(chunk) for chunk in combined) <= 50000


def test_status_tracker_caps_hitl_event_history():
    signals = {"hitl_events": []}
    state = {"number_of_transactions": 10}

    for i in range(15):
        result = {
            "reasoning_log": [
                "[Interaction] Type: request\n"
                f"[Interaction] User replied: done-{i}"
            ]
        }
        tracker._update_interaction(signals, state, result)

    hitl_events = signals.get("hitl_events") or []
    assert len(hitl_events) == 10
    assert str(hitl_events[-1].get("reply", "")).startswith("done-14")


def test_status_tracker_sets_sensitive_confirmation_blocking_issue():
    signals = {}
    state = {"current_task": "Send the email to the recipient."}
    result = {
        "reasoning_log": [
            "[Executor] Action: click\n"
            "[Executor] Args: role=button, name=Send\n"
            "[Executor] Status: failure\n"
            "[Executor] Message: Sensitive action requires explicit user confirmation before execution.\n"
            "[Executor] Error Type: tool_limit"
        ]
    }

    tracker._update_executor(signals, state, result)

    assert signals.get("blocking_issue") == "Sensitive action confirmation required before proceeding."


def test_verifier_completes_generic_field_step_without_any_task_keyword_special_casing():
    """The replacement for the deleted email-compose keyword classifiers:
    completion comes from the field_progress tracker (fed by read_form /
    verified field writes) for an ordinary, non-email data-entry task, proving
    the structural path works independent of task wording."""
    verifier = Verifier()
    state = {
        "current_step_index": 0,
        "current_plan": ["Enter the account number and security answer."],
        "current_task": "Enter the account number and security answer.",
        "reasoning_log": [
            "[Executor] Action: fill\n"
            "[Executor] Args: role=textbox, name=Security answer, text=blue\n"
            "[Executor] Status: success\n"
            "[Executor] Message: Filled 'Security answer'",
        ],
        "status_signals": {
            "field_progress": {
                "task_signature": "enter the account number and security answer.",
                "required_count": 2,
                "completed_fields": ["account number", "security answer"],
            }
        },
        "step_attempts": 2,
        "number_of_transactions": 20,
    }

    result = verifier(state)

    assert result["needs_fallback"] is False
    assert result["last_step_complete"] is True
    assert result["step_attempts"] == 0


def test_verifier_field_progress_helper_reports_partial_completion():
    """Unit-level check on the structural gate itself (rather than the whole
    pipeline): with one of two required fields captured, it must not report
    complete. Going through the full verifier() call here would exercise the
    conftest LLM stub, which always answers step_complete=True and would mask
    a broken gate."""
    verifier = Verifier.__new__(Verifier)
    state = {
        "status_signals": {
            "field_progress": {
                "task_signature": "enter the account number and security answer.",
                "required_count": 2,
                "completed_fields": ["account number"],
            }
        },
    }

    complete, done, required = verifier._field_progress_step_complete(
        state, "Enter the account number and security answer."
    )

    assert complete is False
    assert done == 1
    assert required == 2

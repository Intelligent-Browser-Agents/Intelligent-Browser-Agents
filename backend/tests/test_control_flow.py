import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = BACKEND_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from agents.orchestrator import Orchestrator
from agents.verifier import Verifier
from agents.executor import Executor
from agents.interaction import InteractionAgent
import state as state_reducers
import status_tracker as tracker


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


def test_orchestrator_transaction_abort_credit_reduces_effective_load():
    orchestrator = Orchestrator.__new__(Orchestrator)
    state = {
        "step_attempts": 0,
        "max_step_attempts": 6,
        "max_transactions": 10,
        "number_of_transactions": 10,
        "status_signals": {
            "completed_steps": [0, 1, 2],
        },
        "last_step_complete": False,
    }

    reason = orchestrator._get_abort_reason(state)
    assert reason == ""


def test_orchestrator_transaction_abort_still_triggers_when_effective_load_too_high():
    orchestrator = Orchestrator.__new__(Orchestrator)
    state = {
        "step_attempts": 0,
        "max_step_attempts": 6,
        "max_transactions": 10,
        "number_of_transactions": 20,
        "status_signals": {
            "completed_steps": [0, 1, 2],
        },
        "last_step_complete": False,
    }

    reason = orchestrator._get_abort_reason(state)
    assert "effective load" in reason
    assert "Aborted after 20 transactions" in reason


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
        "extracted_content": ["Orlando weather: 78F and partly cloudy with light wind."],
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


def test_executor_detects_non_recipient_compose_content_task():
    assert Executor._is_email_compose_recipient_task(
        "Draft an appropriate subject line and email message content."
    ) is False


def test_verifier_recipient_not_confirmed_by_searchbox_type_and_save_click():
    logs = [
        "[Executor] Action: type\n"
        "[Executor] Args: text=inesculent@gmail.com\n"
        "[Executor] Status: success\n"
        "[Executor] Message: Typed 'inesculent@gmail.com' into tag=input, role=searchbox, label=Search my contacts",
    ]
    last_exec = (
        "[Executor] Action: click\n"
        "[Executor] Args: role=button, name=Save\n"
        "[Executor] Status: success\n"
        "[Executor] Message: Clicked button 'Save'"
    ).lower()

    assert Verifier._recipient_step_confirmed("inesculent@gmail.com", last_exec, logs) is False


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


def test_status_tracker_compose_draft_keeps_first_body_capture():
    signals = {}
    state = {"current_task": "Draft an appropriate subject line and email content about a cool fact about an animal."}

    first = {
        "reasoning_log": [
            "[Executor] Action: type\n"
            "[Executor] Args: text=Cats sleep for around 12 to 16 hours each day.\n"
            "[Executor] Status: success\n"
            "[Executor] Message: Typed into tag=div, role=presentation, label=Message body, contenteditable=true"
        ]
    }
    tracker._update_executor(signals, state, first)

    second = {
        "reasoning_log": [
            "[Executor] Action: type\n"
            "[Executor] Args: text=Octopuses have three hearts and blue blood.\n"
            "[Executor] Status: success\n"
            "[Executor] Message: Typed into tag=div, role=presentation, label=Message body, contenteditable=true"
        ]
    }
    tracker._update_executor(signals, state, second)

    assert signals.get("compose_draft", {}).get("body") == "Cats sleep for around 12 to 16 hours each day."


def test_interaction_parses_sensitive_confirmation_yes_no_unclear():
    assert InteractionAgent._parse_sensitive_confirmation("Yes, proceed") is True
    assert InteractionAgent._parse_sensitive_confirmation("No, cancel it") is False
    assert InteractionAgent._parse_sensitive_confirmation("maybe") is None


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


def test_verifier_recipient_confirmation_persists_from_recent_option_click():
    logs = [
        "[Executor] Action: type\n"
        "[Executor] Args: text=inesculent@gmail.com\n"
        "[Executor] Status: success\n"
        "[Executor] Message: Typed 'inesculent@gmail.com' into tag=div, role=presentation, label=To, contenteditable=true",
        "[Executor] Action: click\n"
        "[Executor] Args: role=option, name=inesculent@gmail.com - inesculent@gmail.com\n"
        "[Executor] Status: success\n"
        "[Executor] Message: Clicked option 'inesculent@gmail.com - inesculent@gmail.com'",
        "[Executor] Action: press_key\n"
        "[Executor] Args: key=Tab\n"
        "[Executor] Status: success\n"
        "[Executor] Message: Pressed 'Tab'",
    ]
    last_exec = logs[-1].lower()

    assert Verifier._recipient_step_confirmed("inesculent@gmail.com", last_exec, logs) is True


def test_verifier_routes_content_step_recipient_drift_to_fallback():
    verifier = Verifier()
    state = {
        "current_step_index": 3,
        "current_plan": [
            "Open a new email draft from the UCF email account.",
            "Fill in the recipient as inesculent@gmail.com.",
            "Draft an appropriate subject line and email content about a cool fact about an animal.",
        ],
        "current_task": "Draft an appropriate subject line and email content about a cool fact about an animal.",
        "reasoning_log": [
            "[Executor] Action: click\n"
            "[Executor] Args: role=button, name=To\n"
            "[Executor] Status: success\n"
            "[Executor] Message: Clicked button 'To'",
        ],
        "status_signals": {
            "compose_fields": {
                "recipient": True,
                "subject": True,
                "body": False,
            }
        },
        "step_attempts": 1,
        "number_of_transactions": 30,
    }

    result = verifier(state)

    assert result["needs_fallback"] is True
    assert result["last_step_complete"] is False


def test_verifier_does_not_treat_subject_click_as_recipient_drift_from_after_state_noise():
    verifier = Verifier()
    state = {
        "current_step_index": 3,
        "current_plan": [
            "Open a new email draft.",
            "Fill in the recipient as inesculent@gmail.com.",
            "Draft a subject line and email body about a cool fact about an animal.",
        ],
        "current_task": "Draft a subject line and email body about a cool fact about an animal.",
        "reasoning_log": [
            "[Executor] Action: click\n"
            "[Executor] Args: role=textbox, name=Subject\n"
            "[Executor] Status: success\n"
            "[Executor] Message: Clicked textbox 'Subject'\n"
            "[Executor] AFTER_STATE (page content for verification):\n"
            "[role=\"textbox\"] \"To\"\n",
        ],
        "status_signals": {
            "compose_fields": {
                "recipient": True,
                "subject": False,
                "body": False,
            }
        },
        "step_attempts": 1,
        "number_of_transactions": 30,
    }

    result = verifier(state)

    assert result["needs_fallback"] is False
    assert result["last_step_complete"] is False


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


def test_verifier_completes_compose_content_step_when_subject_and_body_typed():
    verifier = Verifier()
    state = {
        "current_step_index": 1,
        "current_plan": [
            "Open a new email draft addressed to inesculent@gmail.com.",
            "Draft a suitable subject line and email message content appropriate to the user's request.",
        ],
        "current_task": "Draft a suitable subject line and email message content appropriate to the user's request.",
        "reasoning_log": [
            "[Executor] Action: type\n"
            "[Executor] Args: text=Quick hello from UCF\n"
            "[Executor] Status: success\n"
            "[Executor] Message: Typed 'Quick hello from UCF' into tag=input, label=Subject, placeholder=Add a subject",
            "[Executor] Action: type\n"
            "[Executor] Args: text=Hi, I hope you're doing well. Just wanted to send a quick hello from my UCF email.\n"
            "[Executor] Status: success\n"
            "[Executor] Message: Typed into tag=div, role=textbox, label=Message body, contenteditable=true",
        ],
        "step_attempts": 4,
        "number_of_transactions": 40,
    }

    result = verifier(state)

    assert result["needs_fallback"] is False
    assert result["is_complete"] is False
    assert result["last_step_complete"] is True
    assert result["step_attempts"] == 0


def test_verifier_keeps_compose_content_step_in_progress_when_only_subject_typed():
    verifier = Verifier()
    state = {
        "current_step_index": 1,
        "current_plan": [
            "Open a new email draft addressed to inesculent@gmail.com.",
            "Draft a suitable subject line and email message content appropriate to the user's request.",
        ],
        "current_task": "Draft a suitable subject line and email message content appropriate to the user's request.",
        "reasoning_log": [
            "[Executor] Action: type\n"
            "[Executor] Args: text=Quick hello from UCF\n"
            "[Executor] Status: success\n"
            "[Executor] Message: Typed 'Quick hello from UCF' into tag=input, label=Subject, placeholder=Add a subject",
        ],
        "step_attempts": 1,
        "number_of_transactions": 34,
    }

    result = verifier(state)

    assert result["needs_fallback"] is False
    assert result["last_step_complete"] is False


def test_verifier_does_not_count_recipient_contenteditable_text_as_body_completion():
    verifier = Verifier()
    state = {
        "current_step_index": 2,
        "current_plan": [
            "Open a new email draft.",
            "Address the email to inesculent@gmail.com.",
            "Draft an appropriate subject line and email message content.",
        ],
        "current_task": "Draft an appropriate subject line and email message content.",
        "reasoning_log": [
            "[Executor] Action: type\n"
            "[Executor] Args: text=inesculent@gmail.com\n"
            "[Executor] Status: success\n"
            "[Executor] Message: Typed 'inesculent@gmail.com' into tag=div, role=presentation, label=To, contenteditable=true",
            "[Executor] Action: type\n"
            "[Executor] Args: text=Hello from UCF\n"
            "[Executor] Status: success\n"
            "[Executor] Message: Typed 'Hello from UCF' into tag=input, label=Subject, placeholder=Add a subject",
        ],
        "step_attempts": 2,
        "number_of_transactions": 40,
    }

    result = verifier(state)

    assert result["last_step_complete"] is False


def test_verifier_does_not_complete_mixed_compose_step_on_recipient_only():
    verifier = Verifier()
    state = {
        "current_step_index": 1,
        "current_plan": [
            "Open the email composition flow from the user's UCF email account.",
            "Use the inline draft and populate To, Subject, and message body.",
        ],
        "current_task": "Use the inline draft and populate To, Subject, and message body.",
        "reasoning_log": [
            "[Executor] Action: type\n"
            "[Executor] Args: text=inesculent@gmail.com\n"
            "[Executor] Status: success\n"
            "[Executor] Message: Typed 'inesculent@gmail.com' into tag=input, role=combobox, label=Search for email, placeholder=Add recipients",
        ],
        "step_attempts": 2,
        "number_of_transactions": 67,
    }

    result = verifier(state)

    assert result["needs_fallback"] is False
    assert result["last_step_complete"] is False


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


def test_status_tracker_infers_subject_and_body_for_generic_write_email_step():
    signals = {}
    state = {
        "current_step_index": 0,
        "current_task": "Write an email about a cool fact involving an animal.",
    }
    result = {
        "current_step_index": 0,
        "current_task": "Write an email about a cool fact involving an animal.",
    }

    tracker._update_orchestrator(signals, state, result)

    progress = signals.get("field_progress") or {}
    assert progress.get("required_count") == 2
    assert set(progress.get("named_required_fields") or []) >= {"subject", "body"}


def test_verifier_does_not_complete_recipient_step_from_generic_field_progress_only():
    verifier = Verifier()
    state = {
        "current_step_index": 2,
        "current_plan": [
            "Open a new email draft.",
            "Enter inesculent@gmail.com as the recipient.",
        ],
        "current_task": "Enter inesculent@gmail.com as the recipient.",
        "reasoning_log": [
            "[Executor] Action: type\n"
            "[Executor] Args: text=inesculent@gmail.com\n"
            "[Executor] Status: success\n"
            "[Executor] Message: Typed 'inesculent@gmail.com' into tag=input, label=Search my contacts, placeholder=Search for email"
        ],
        "status_signals": {
            "field_progress": {
                "task_signature": "enter inesculent@gmail.com as the recipient.",
                "required_count": 1,
                "completed_fields": ["search my contacts"],
            }
        },
        "step_attempts": 1,
        "number_of_transactions": 20,
    }

    result = verifier(state)

    assert result["last_step_complete"] is False

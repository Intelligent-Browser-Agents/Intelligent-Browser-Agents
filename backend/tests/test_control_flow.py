import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = BACKEND_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from agents.orchestrator import Orchestrator
from agents.verifier import Verifier
from agents.executor import Executor
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

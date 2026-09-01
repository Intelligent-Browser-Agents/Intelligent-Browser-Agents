import pytest

from agents.orchestrator import Orchestrator
from agents.verifier import Verifier
from agents.executor import Executor
from agents.interaction import InteractionAgent
from execution.models import ExecutionOutput
from schema import OrchestratorPlan
import state as state_reducers
import status_tracker as tracker


@pytest.mark.llm
def test_verifier_marks_success_and_resets_attempts():
    """A step the page itself confirms resets the attempt counter.

    The state carries `current_url` and an AFTER_STATE block because that is
    what a real navigate produces, and since Phase 3 the verifier judges on
    page evidence rather than on the executor's own claim of success. Without
    them this test asserted that an unverifiable "Status: success" line is
    enough, which is the behaviour Phase 3 deliberately removed.
    """
    verifier = Verifier()
    state = {
        "current_step_index": 0,
        "current_plan": ["Navigate to https://ucf.edu"],
        "current_task": "Navigate to https://ucf.edu",
        "mission_goal": "Open the UCF homepage.",
        "current_url": "https://www.ucf.edu/",
        "reasoning_log": [
            "[Executor] Action: navigate\n"
            "[Executor] Args: url=https://ucf.edu\n"
            "[Executor] Status: success\n"
            "[Executor] Message: Navigated to https://ucf.edu\n"
            "[Executor] AFTER_STATE (page content for verification):\n"
            'URL: https://www.ucf.edu/\n'
            '[role="heading"] "University of Central Florida"\n'
            '[role="link"] "Academics"\n'
            '[role="link"] "Admissions"\n'
            '[role="searchbox"] "Search UCF"'
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


def test_orchestrator_create_plan_populates_work_items_from_bulk_request():
    orchestrator = Orchestrator.__new__(Orchestrator)
    orchestrator.planning_prompt = "test"

    class _Planner:
        def invoke(self, _messages):
            return type("Plan", (), {
                "needs_clarification": False,
                "clarifying_questions": [],
                "goal": "Apply to three job postings",
                "steps": [
                    "Open the application page.",
                    "Fill the application form.",
                    "Submit the application.",
                ],
                "work_items": [
                    {"description": "Apply to Acme", "url": "https://jobs.example.com/acme"},
                    {"description": "Apply to Bravo", "url": "https://jobs.example.com/bravo"},
                    {"description": "Apply to Charlie", "url": "https://jobs.example.com/charlie"},
                ],
            })()

    orchestrator.planner = _Planner()
    state = {
        "messages": [{
            "role": "user",
            "content": (
                "apply to these 3 job postings: "
                "https://jobs.example.com/acme, "
                "https://jobs.example.com/bravo, "
                "https://jobs.example.com/charlie"
            ),
        }],
        "current_url": "about:blank",
        "number_of_transactions": 0,
        "dom_cache": [],
        "last_page_snapshot": "",
    }

    out = orchestrator._create_plan("apply to these 3 job postings", state)

    assert len(out["work_items"]) == 3
    assert out["current_item_index"] == 0
    assert out["work_items"][0]["url"] == "https://jobs.example.com/acme"
    assert out["current_task"] == "Open the application page."


def test_orchestrator_plan_schema_uses_typed_work_items_not_freeform_dicts():
    schema = OrchestratorPlan.model_json_schema()
    work_items = schema["properties"]["work_items"]
    item_ref = work_items["items"]["$ref"]
    assert item_ref == "#/$defs/WorkItem"
    item_schema = schema["$defs"]["WorkItem"]
    assert item_schema["properties"]["description"]["type"] == "string"
    assert item_schema["properties"]["url"]["anyOf"][0]["type"] == "string"


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


def test_executor_allows_save_click_during_data_entry_step():
    executor = Executor.__new__(Executor)
    normalized = executor._normalize_tool_args(
        "click",
        {"role": "button", "name": "Save"},
        "Save the job application draft.",
    )
    assert normalized == {"role": "button", "name": "Save"}


def test_executor_missing_required_field_names_parses_generic_form_report():
    executor = Executor.__new__(Executor)
    report = "\n".join([
        '6 field(s), 3 still empty.',
        '- text "Full name": filled (12 chars) [required]',
        '- email "Email": empty [required]',
        '- textarea "Message to hiring manager": empty',
        '- file "Resume": no file [required]',
        '- checkbox "I accept the terms": unchecked [required]',
    ])

    assert executor._missing_required_field_names(report) == [
        "Email",
        "Resume",
        "I accept the terms",
    ]


@pytest.mark.asyncio
async def test_executor_does_not_block_continue_review_send_finish_for_job_message_step(monkeypatch):
    """Regression for the August 3, 2026 reproduction where a job-application
    step mentioning a message field caused Continue, Review, Send, and Finish
    to deadlock behind the deleted email-specific gate."""
    executor = Executor.__new__(Executor)
    page = object()
    state = {
        "step_intent": "interact",
        "current_task": "Enter your message to the hiring manager, then continue",
    }

    class _ReadFormResult:
        status = "success"
        extracted_text = '3 field(s), 0 still empty.\n- textarea "Message to hiring manager": empty'

    async def fake_read_form(_page):
        return _ReadFormResult()

    monkeypatch.setattr("execution.actions.do_read_form", fake_read_form)

    for name in ("Continue", "Review", "Send", "Finish"):
        blocked = await executor._required_empty_fields_before_finalization(
            page,
            state,
            "click",
            {"role": "button", "name": name},
        )
        assert blocked == []


@pytest.mark.asyncio
async def test_executor_blocks_finalize_when_required_fields_are_empty(monkeypatch):
    executor = Executor.__new__(Executor)
    page = object()
    state = {
        "step_intent": "finalize",
        "current_task": "Submit the job application.",
    }

    class _ReadFormResult:
        status = "success"
        extracted_text = "\n".join([
            "4 field(s), 2 still empty.",
            '- email "Email": empty [required]',
            '- file "Resume": no file [required]',
            '- text "Full name": filled (11 chars) [required]',
        ])

    async def fake_read_form(_page):
        return _ReadFormResult()

    monkeypatch.setattr("execution.actions.do_read_form", fake_read_form)

    blocked = await executor._required_empty_fields_before_finalization(
        page,
        state,
        "click",
        {"role": "button", "name": "Submit application"},
    )
    assert blocked == ["Email", "Resume"]


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


def test_executor_sensitive_action_reason_uses_autonomy_policy_not_submit_token():
    reason = Executor._sensitive_action_reason(
        "click",
        {"role": "button", "name": "Continue"},
        "Submit the job application.",
    )
    assert reason is None


def test_executor_sensitive_action_reason_uses_autonomy_policy_for_submission_button():
    reason = Executor._sensitive_action_reason(
        "click",
        {"role": "button", "name": "Submit application"},
        "Continue with the application.",
    )
    assert isinstance(reason, str) and reason


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


@pytest.mark.asyncio
async def test_executor_finish_from_result_publishes_snapshot_and_verified_flag(monkeypatch):
    executor = Executor.__new__(Executor)
    executor.runtime = {}
    executor._secret_values = ()

    async def fake_snapshot(_page, max_chars=0, section=1):
        return f"[snapshot max={max_chars} section={section}]"

    monkeypatch.setattr(executor, "_get_real_dom_snapshot", fake_snapshot)
    monkeypatch.setattr(executor, "_is_anti_bot_page", lambda _url: False)
    monkeypatch.setattr(executor, "_should_capture_recovery_screenshot", lambda **_kwargs: False)
    monkeypatch.setattr(executor, "_build_execution_log", lambda **kwargs: f"log:{kwargs['status']}")

    class _DomExtractor:
        @staticmethod
        async def get_page_text(_page, max_chars=3500):
            return "Visible text"

    monkeypatch.setattr("agents.executor.dom_extractor", _DomExtractor)

    page = type("Page", (), {
        "url": "https://jobs.example.com/apply",
        "context": type("Context", (), {"pages": []})(),
    })()
    result = ExecutionOutput(
        action="click",
        args={"role": "button", "name": "Continue"},
        status="success",
        error_type="none",
        message="Clicked Continue",
        execution_time_ms=12,
        verified=True,
    )

    out = await executor._finish_from_result(
        state={"number_of_transactions": 4},
        page=page,
        current_url="https://jobs.example.com/apply",
        result=result,
    )

    assert out["last_page_snapshot"] == "[snapshot max=3500 section=1]"
    assert out["last_execution_event"]["verified"] is True


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


def test_status_tracker_survives_a_successful_executor_action():
    """Regression: the success branch feeds ev_args from the structured event
    into _feed_field_progress. A cleanup once deleted the ev_args assignment
    while the call site kept using it, so every SUCCESSFUL action raised
    NameError inside the node wrapper and killed the run; the only test at the
    time used Status: failure and never entered the branch."""
    signals = {}
    state = {"current_task": "Fill in the applicant's email address."}
    result = {
        "reasoning_log": [
            "[Executor] Action: fill\n"
            "[Executor] Args: role=textbox, name=Email, text=me@example.com\n"
            "[Executor] Status: success\n"
            "[Executor] Message: Filled 'Email' and confirmed by readback."
        ],
        "last_execution_event": {
            "action": "fill",
            "args": {"role": "textbox", "name": "Email", "text": "me@example.com"},
            "status": "success",
            "error_type": None,
            "message": "Filled 'Email' and confirmed by readback.",
            "verified": True,
        },
    }

    tracker._update_executor(signals, state, result)

    assert signals.get("last_action", {}).get("status") == "success"


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

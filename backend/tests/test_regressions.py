"""
Regression tests for confirmed defects in docs/IMPROVEMENT_PLAN.md.

Each test here pins a bug that was found, diagnosed, and fixed, so that it
cannot come back quietly. Phase 8 names six; the other four already have a home
next to the behaviour they constrain, and are cross-referenced at the bottom of
this file so the set stays auditable from one place.

New entries belong here when the defect is not a natural fit for any existing
module's test file, or when the thing being protected is a project-level
invariant rather than a function's behaviour.
"""

from __future__ import annotations

import pathlib

import pytest

from schema import ExecutionArgs


# ---------------------------------------------------------------------------
# The Google URL rewrite
#
# `_is_google_url` matched every host ending in `.google.com` and rewrote the
# navigation target to `https://duckduckgo.com`. Google Forms is a common
# application host and `accounts.google.com` is the "Sign in with Google" hop on
# Greenhouse, Lever, and Workday, so an application behind either was
# unfinishable. See docs/IMPROVEMENT_PLAN.md lines 26-36.
# ---------------------------------------------------------------------------

def _normalized_navigate_url(url: str, task: str, user_intent: str = "") -> str:
    """Run a navigate action through the executor's real normalization path.

    Built with `__new__` because none of the navigate branch touches the runtime,
    the models, or the prompts, and constructing a real Executor would require
    all three.
    """
    from agents.executor import Executor
    from schema import ExecutionArgs, ExecutionResult

    executor = Executor.__new__(Executor)
    action = ExecutionResult(
        action="navigate",
        args=ExecutionArgs(url=url),
        status="success",
        error_type="none",
        message="",
    )
    result = executor._validate_and_normalize_action(
        action, current_task=task, dom_snapshot="", user_intent=user_intent
    )
    return result.args.url


@pytest.mark.parametrize(
    "url",
    [
        "https://mail.google.com/",
        "https://docs.google.com/forms/d/e/1FAIpQLSc/viewform",
        "https://accounts.google.com/signin",
        "https://drive.google.com/file/d/abc/view",
        "https://calendar.google.com/",
    ],
)
def test_regression_google_owned_hosts_are_not_rewritten(url):
    """A step that never says "google" must still reach these verbatim."""
    assert _normalized_navigate_url(url, task="Continue the application.") == url


def test_regression_a_google_forms_application_is_reachable():
    """The case from the plan: Google Forms is a common application host."""
    url = "https://docs.google.com/forms/d/e/1FAIpQLSc/viewform"

    assert _normalized_navigate_url(url, task="Fill out the employer questionnaire.") == url


def test_regression_the_sign_in_with_google_hop_is_reachable():
    """`accounts.google.com` is the SSO hop on Greenhouse, Lever, and Workday."""
    url = "https://accounts.google.com/signin"

    assert _normalized_navigate_url(url, task="Sign in to continue the application.") == url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.google.com", "https://duckduckgo.com"),
        ("https://www.google.com/", "https://duckduckgo.com"),
        ("https://google.com/search?q=ucf+tuition", "https://duckduckgo.com/?q=ucf+tuition"),
    ],
)
def test_google_search_entry_points_are_still_diverted(url, expected):
    """The anti-bot interstitial is real, so the rewrite stays for search itself."""
    assert _normalized_navigate_url(url, task="Look up the tuition rate.") == expected


def test_regression_a_diverted_search_keeps_its_query():
    """Rewriting to a bare homepage dropped the search terms, which reads as a
    successful navigation while losing the step's entire purpose."""
    assert (
        _normalized_navigate_url("https://www.google.com/search?q=ucf+tuition", task="Look it up.")
        == "https://duckduckgo.com/?q=ucf+tuition"
    )


def test_an_explicit_request_for_google_search_is_honoured():
    """The existing escape hatch: naming Google in the step keeps the target."""
    url = "https://www.google.com/search?q=ucf"

    assert _normalized_navigate_url(url, task="Search google for UCF.") == url


# ---------------------------------------------------------------------------
# The `execution` package shadow
#
# `backend/tests/execution/__init__.py` made `execution` an importable top-level
# package that shadowed `backend/src/execution`, which aborted collection for
# the entire suite. The fix was `--import-mode=importlib` in pyproject.toml,
# which nothing asserted, so deleting that line would silently reintroduce it.
# ---------------------------------------------------------------------------

def test_regression_the_execution_package_is_not_shadowed_by_the_test_package():
    import execution

    resolved = pathlib.Path(execution.__file__).resolve()
    assert resolved.parent.name == "execution"
    assert resolved.parent.parent.name == "src", (
        f"`execution` resolved to {resolved}, not backend/src/execution. The test "
        "package under backend/tests/execution/ is shadowing it again; check that "
        "--import-mode=importlib is still set in pyproject.toml."
    )


def test_regression_the_real_execution_package_exports_the_action_layer():
    """Resolving to the right directory is not enough; it has to be the module
    the rest of the code imports."""
    from execution import Action, ActionArgs, dispatch_action

    assert callable(dispatch_action)
    assert Action and ActionArgs


# ---------------------------------------------------------------------------
# The `file_path` alias on `ExecutionArgs.document_id`
#
# `execution_tools.prompt.md` documents the argument as `upload_file(file_path=...)`
# while the JSON schema field is `document_id`. Without the alias the value is
# dropped during validation and the upload fails with "No file was provided",
# which reads as a page problem rather than a schema mismatch.
# ---------------------------------------------------------------------------

def test_regression_upload_file_accepts_the_file_path_argument_name():
    args = ExecutionArgs.model_validate({"file_path": "/tmp/resume.pdf"})

    assert args.document_id == "/tmp/resume.pdf"


def test_the_canonical_document_id_name_still_works():
    args = ExecutionArgs.model_validate({"document_id": "/tmp/resume.pdf"})

    assert args.document_id == "/tmp/resume.pdf"


def test_document_id_serializes_under_its_canonical_name():
    args = ExecutionArgs.model_validate({"file_path": "/tmp/resume.pdf"})

    assert args.model_dump(by_alias=True)["document_id"] == "/tmp/resume.pdf"


def test_the_prompt_and_the_schema_agree_on_the_upload_argument():
    """The alias only helps if the prompt keeps naming one of the two spellings."""
    from prompt_loader import get_execution_tools_prompt

    prompt = get_execution_tools_prompt()
    assert "file_path" in prompt
    assert ExecutionArgs.model_validate({"file_path": "/tmp/x.pdf"}).document_id


# ---------------------------------------------------------------------------
# The other confirmed defects, and where they are pinned
#
# These live next to the behaviour they constrain rather than here. The test
# below fails if one is renamed or removed, so the six-item set in Phase 8 of
# docs/IMPROVEMENT_PLAN.md stays auditable from one place.
# ---------------------------------------------------------------------------

CROSS_REFERENCED = {
    # The compose gate blocked a job application's "Continue" click, because the
    # send/finish guard treated any job-message step as an email compose.
    "test_control_flow.py": [
        "test_executor_does_not_block_continue_review_send_finish_for_job_message_step",
        # The budget arithmetic: every node incremented the transaction counter
        # while the abort test subtracted "success credits", pushing the graceful
        # stop past LangGraph's own recursion limit.
        "test_orchestrator_transaction_abort_is_a_plain_counter",
    ],
    # The AFTER_STATE strip: the verifier overwrote the tail of the real log with
    # a synthetic event that carried no page content, then judged the current
    # action using the previous action's snapshot.
    "test_verifier_login_guard.py": [
        "test_regression_verifier_no_longer_overwrites_the_log_tail",
        "test_regression_the_prompt_receives_after_state",
    ],
    # The login auth bypass: a valid Authorization header short-circuited the
    # password check and returned a token for whoever the header belonged to.
    "test_server.py": [
        "test_regression_login_header_does_not_bypass_password_check",
    ],
}


@pytest.mark.parametrize(
    ("module", "test_name"),
    [(module, name) for module, names in CROSS_REFERENCED.items() for name in names],
)
def test_the_cross_referenced_regressions_still_exist(module, test_name):
    source = (pathlib.Path(__file__).parent / module).read_text(encoding="utf-8")

    assert f"def {test_name}(" in source, (
        f"{module}::{test_name} is named in Phase 8 of docs/IMPROVEMENT_PLAN.md as the "
        "regression test for a confirmed bug, and it is no longer there. If it was "
        "renamed, update CROSS_REFERENCED in this file; if it was deleted, the bug is "
        "unguarded again."
    )

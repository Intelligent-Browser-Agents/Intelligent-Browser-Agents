"""
Verifier evidence and the authentication guard.

Two defects met here on a real MyUCF run.

The verifier discarded its own page evidence: `last_execution_event` was rendered
into a synthetic log with no AFTER_STATE, and that string *replaced* the tail of
the real executor log. The prompt still told the model AFTER_STATE was present and
to prefer it, so the verifier judged each action using the previous action's page
content.

With that evidence missing and the verifier sampling at temperature 0.3, arriving
at an identity provider's sign-in form was accepted as "login complete". The
orchestrator advanced to the grades step, could not proceed, and the run ended
asking the user to sign in by hand.
"""

import inspect

import pytest

from agents.verifier import Verifier


AFTER_STATE_LOGIN_FORM = (
    "[Executor] Action: click\n"
    "[Executor] Args: role=link, name=Log In\n"
    "[Executor] Status: success\n"
    "[Executor] Message: Clicked link 'Log In'\n"
    "[Executor] AFTER_STATE (page content for verification):\n"
    '[role="img"] "Microsoft"\n'
    '[role="textbox"] "someone@example.com"\n'
    '[role="textbox"] "Password"\n'
    '[role="button"] "Sign in"'
)

AFTER_STATE_SIGNED_IN = (
    "[Executor] Action: click\n"
    "[Executor] Args: role=link, name=Student Self Service\n"
    "[Executor] Status: success\n"
    "[Executor] Message: Clicked link 'Student Self Service'\n"
    "[Executor] AFTER_STATE (page content for verification):\n"
    '[role="heading"] "Student Center"\n'
    '[role="menuitem"] "View My Grades / GPA"'
)


def _login_state(**overrides):
    state = {
        "current_task": "Log in to MyUCF using saved credentials.",
        "step_intent": "authenticate",
    }
    state.update(overrides)
    return state


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------

def test_guard_fires_while_a_password_field_is_still_on_screen():
    assert Verifier._credentials_still_requested(_login_state(), AFTER_STATE_LOGIN_FORM) is True


def test_guard_clears_once_the_page_is_past_the_login_form():
    assert Verifier._credentials_still_requested(_login_state(), AFTER_STATE_SIGNED_IN) is False


def test_guard_only_applies_to_authentication_steps():
    """A non-login step must not be blocked just because a password field exists."""
    state = {"current_task": "Fill in the application form.", "step_intent": "compose"}
    assert Verifier._credentials_still_requested(state, AFTER_STATE_LOGIN_FORM) is False


def test_guard_recognises_login_steps_without_a_step_intent():
    """step_intent is not always populated; the task text is a fallback signal."""
    state = {"current_task": "Sign in to the portal.", "step_intent": ""}
    assert Verifier._credentials_still_requested(state, AFTER_STATE_LOGIN_FORM) is True


def test_guard_does_not_override_when_there_is_no_page_evidence():
    """Without AFTER_STATE there is nothing to judge, so leave the model's verdict."""
    no_evidence = (
        "[Executor] Action: click\n"
        "[Executor] Args: role=link, name=Log In\n"
        "[Executor] Status: success\n"
        "[Executor] Message: Clicked link 'Log In'"
    )
    assert Verifier._credentials_still_requested(_login_state(), no_evidence) is False


@pytest.mark.parametrize("task", ["Log in to MyUCF", "sign-in to the portal", "Authenticate with SSO"])
def test_guard_matches_common_login_phrasings(task):
    assert Verifier._credentials_still_requested(
        {"current_task": task, "step_intent": ""}, AFTER_STATE_LOGIN_FORM
    ) is True


# ---------------------------------------------------------------------------
# Evidence plumbing
# ---------------------------------------------------------------------------

def test_regression_verifier_no_longer_overwrites_the_log_tail():
    """The synthetic log must not replace the entry that carries AFTER_STATE."""
    source = inspect.getsource(Verifier.__call__)
    assert "recent_executor_logs[:-1] + [syn]" not in source
    assert "last_execution_structured" in source


def test_regression_the_prompt_receives_after_state():
    """`last_execution` goes into the prompt and must prefer the raw log entry."""
    source = inspect.getsource(Verifier.__call__)
    prompt_line = 'self._clip_text(last_execution, 2200)'
    assert prompt_line in source, "prompt no longer interpolates last_execution"
    # And last_execution must come from the raw log, not the synthetic renderer.
    assert "last_execution = recent_executor_logs[-1]" in source


def test_regression_deterministic_guards_use_the_structured_view():
    """Keyword guards must not match words appearing in page copy."""
    source = inspect.getsource(Verifier.__call__)
    assert "last_exec_lower = (last_execution_structured or \"\").lower()" in source


def test_control_plane_is_configured_deterministically():
    """verifier.step_complete and verifier.handoff are graph edges, not prose.

    Note this asserts configuration only. See the test below: the value does not
    reach the API on the reasoning models currently in use.
    """
    from models import TEMPERATURES

    for agent in ("verifier", "decision", "fallback", "executor"):
        assert TEMPERATURES[agent] == 0.0, f"{agent} must be deterministic, got {TEMPERATURES[agent]}"


def test_temperature_is_inert_on_the_configured_reasoning_models():
    """Pins a limitation that is easy to forget and gives false confidence.

    gpt-5.x accepts only temperature=1.0 and langchain-openai silently drops any
    other value, so TEMPERATURES does nothing for the current AGENT_MODELS. Anyone
    relying on "we set temperature 0, so the control plane is deterministic" is
    mistaken; determinism has to come from structural guards instead.

    If this ever fails, temperature became honourable again and the surrounding
    comments in models.py should be revisited.
    """
    # Built directly rather than through get_llm, which conftest stubs out.
    # Construction performs no network call.
    from langchain_openai import ChatOpenAI

    from models import AGENT_MODELS, MODELS

    model_name = MODELS[AGENT_MODELS["verifier"]].name
    model = ChatOpenAI(model=model_name, temperature=0.0, api_key="test-key-not-used")

    assert model.temperature is None, (
        f"temperature now reaches {model_name}; update the note in models.py and "
        "reconsider how much the structural guards need to carry"
    )

"""
Secret redaction tests.

`handle_type` used to report `Typed '<value>' into <field>`. That message is not
covered by the args redaction in `Executor._execution_output_for_log`, so a typed
password reached `reasoning_log`, and `Executor._build_recent_actions` then fed
`reasoning_log` back into the model prompt on every subsequent turn.
"""

from agents.executor import Executor
from execution.models import ExecutionOutput


VAULT = {
    "user_credentials": {
        "fullName": "Ada Lovelace",
        "userCredentialsList": [
            {"serviceName": "workday", "username": "ada@example.com", "password": "Tr0ub4dor&3"},
        ],
        "userPaymentMethods": [
            {"cardNumber": "4111111111111111", "cvv": "123"},
        ],
    }
}


def _executor_with_vault(state=VAULT):
    executor = Executor.__new__(Executor)
    executor._secret_values = Executor._collect_secret_values(state)
    return executor


def test_collect_secret_values_picks_up_passwords_and_card_numbers():
    secrets = Executor._collect_secret_values(VAULT)
    assert "Tr0ub4dor&3" in secrets
    assert "4111111111111111" in secrets
    assert "123" not in secrets  # too short to redact safely


def test_collect_secret_values_tolerates_missing_vault():
    assert Executor._collect_secret_values({}) == ()
    assert Executor._collect_secret_values({"user_credentials": None}) == ()


def test_execution_log_redacts_a_typed_password():
    executor = _executor_with_vault()
    log = executor._build_execution_log(
        action="type",
        args={"text": "Tr0ub4dor&3", "target_name": "Password"},
        status="success",
        message="Typed 11 character(s) into tag=input, role=textbox, label=Password",
    )
    assert "Tr0ub4dor&3" not in log
    assert "<redacted len=11>" in log


def test_execution_log_redacts_a_password_embedded_in_a_message():
    executor = _executor_with_vault()
    log = executor._build_execution_log(
        action="type",
        args={},
        status="failure",
        message="Failed to type: could not fill 'Tr0ub4dor&3' into the field",
        error_type="tool_limit",
    )
    assert "Tr0ub4dor&3" not in log


def test_execution_log_leaves_ordinary_text_intact():
    """Redaction is by exact secret value, so functional text must survive."""
    executor = _executor_with_vault()
    log = executor._build_execution_log(
        action="type",
        args={"text": "Dear hiring manager, I am excited to apply"},
        status="success",
        message="Typed 41 character(s) into tag=textarea, label=Cover letter",
    )
    assert "Dear hiring manager, I am excited to apply" in log


def test_output_for_log_redacts_args_and_message():
    executor = _executor_with_vault()
    payload = executor._execution_output_for_log(
        ExecutionOutput(
            action="type",
            args={"text": "Tr0ub4dor&3"},
            status="success",
            error_type="none",
            message="Typed 'Tr0ub4dor&3' into label=Password",
            execution_time_ms=5,
            extracted_text="page text",
        )
    )
    assert payload["args"]["text"].startswith("<redacted")
    assert "Tr0ub4dor&3" not in payload["message"]
    assert payload["extracted_text"].startswith("<redacted")


def test_redaction_is_a_noop_without_a_vault():
    executor = _executor_with_vault({})
    log = executor._build_execution_log(
        action="type", args={"text": "hello"}, status="success", message="Typed 5 character(s)"
    )
    assert "hello" in log


def test_handle_type_success_message_does_not_contain_the_typed_value():
    """Guards the handler itself, independent of executor-level redaction."""
    import inspect

    from execution import handlers

    source = inspect.getsource(handlers.handle_type)
    assert "Typed '{text}'" not in source
    assert "f\"Typed {len(text)} character(s)" in source


def test_server_does_not_log_hitl_reply_contents():
    """A clarification reply can carry an MFA code or a password.

    The stream endpoint used to print `content[:200]` for every reply, so those
    landed in the server log.
    """
    import inspect

    import server

    source = inspect.getsource(server.stream_endpoint)
    assert "content[:200]" not in source
    assert "{str(user_input)[:200]}" not in source
    assert "len(content)} chars" in source


def test_server_does_not_log_the_credential_blob():
    """`print(f"[STREAM] session_id=... credentials={credentials}")` dumped every
    saved password to stdout on every run."""
    import inspect

    import server

    source = inspect.getsource(server.stream_endpoint)
    assert "credentials={credentials}" not in source
    assert "credential_keys=" in source

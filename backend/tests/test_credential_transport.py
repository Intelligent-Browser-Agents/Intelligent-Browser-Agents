"""
Credential transport tests.

Credentials used to be handed to the agent as a `--credentials_json` command-line
argument. On both Linux (`/proc/<pid>/cmdline`) and Windows (the process list),
that is readable by other processes, so a saved password was exposed to anything
running on the same machine. They now travel over the subprocess's stdin.

The parser is exercised in-process, and then as a real subprocess so the argument
surface is checked against the actual CLI rather than a mock.
"""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
APP_PATH = BACKEND_DIR / "src" / "app.py"


def _read_with_stdin(monkeypatch, text):
    """Run app.read_credentials_from_stdin against a fake stdin."""
    import io

    import app

    monkeypatch.setattr(app.sys, 'stdin', io.StringIO(text))
    return app.read_credentials_from_stdin()


def test_reads_a_credential_blob(monkeypatch):
    payload = {"fullName": "Ada", "userCredentialsList": [{"serviceName": "x"}]}
    assert _read_with_stdin(monkeypatch, json.dumps(payload) + "\n") == payload


def test_empty_stdin_yields_empty_credentials(monkeypatch):
    """EOF must not hang or raise: the run continues without saved credentials."""
    assert _read_with_stdin(monkeypatch, "") == {}


def test_blank_line_yields_empty_credentials(monkeypatch):
    assert _read_with_stdin(monkeypatch, "\n") == {}


def test_malformed_json_yields_empty_credentials(monkeypatch):
    assert _read_with_stdin(monkeypatch, "{not json\n") == {}


def test_non_object_json_yields_empty_credentials(monkeypatch):
    assert _read_with_stdin(monkeypatch, '["a", "b"]\n') == {}


def test_only_the_first_line_is_consumed(monkeypatch):
    """Later lines belong to the HITL reply channel and must be left alone."""
    import io

    import app

    stream = io.StringIO('{"fullName": "Ada"}\n{"user_input": "yes"}\n')
    monkeypatch.setattr(app.sys, 'stdin', stream)
    assert app.read_credentials_from_stdin() == {"fullName": "Ada"}
    assert stream.readline() == '{"user_input": "yes"}\n'


def test_regression_cli_rejects_credentials_on_the_command_line():
    """`--credentials_json` must no longer exist as an argument."""
    result = subprocess.run(
        [sys.executable, str(APP_PATH), "--help"],
        capture_output=True,
        text=True,
        cwd=str(BACKEND_DIR),
    )
    assert result.returncode == 0, result.stderr
    assert "--credentials_json" not in result.stdout
    assert "--prompt" in result.stdout
    assert "--port" in result.stdout


def test_regression_secrets_are_not_visible_in_the_child_command_line(tmp_path):
    """End-to-end: a real child process reads the blob from stdin, and its own
    command line contains no trace of it."""
    script = tmp_path / "probe.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import json, sys
            sys.path.insert(0, {str(BACKEND_DIR / "src")!r})
            from app import read_credentials_from_stdin
            creds = read_credentials_from_stdin()
            print(json.dumps({{
                "password": creds.get("userCredentialsList", [{{}}])[0].get("password"),
                "argv": sys.argv[1:],
            }}))
            """
        ),
        encoding="utf-8",
    )

    secret = "Tr0ub4dor&3-unique-marker"
    blob = {"userCredentialsList": [{"serviceName": "workday", "password": secret}]}

    process = subprocess.Popen(
        [sys.executable, str(script), "--prompt", "apply to jobs", "--port", "9000"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = process.communicate(
        (json.dumps(blob) + "\n").encode("utf-8"), timeout=60
    )
    assert process.returncode == 0, stderr.decode()

    result = json.loads(stdout.decode().strip().splitlines()[-1])
    # The child received the secret...
    assert result["password"] == secret
    # ...and it was never an argument.
    assert not any(secret in arg for arg in result["argv"])


@pytest.mark.parametrize(
    "blob",
    [
        {},
        {"fullName": "Ada"},
        # A value containing a literal newline would split the frame in two and
        # desynchronise the HITL channel that reads subsequent lines.
        {"address": "1 Main St\nApt 2", "note": "line1\r\nline2"},
        {"nested": [{"password": "a\nb"}]},
    ],
)
def test_credential_line_survives_a_round_trip(monkeypatch, blob):
    """The child reads exactly one line, so the encoding must never emit more.

    `json.dumps` escapes newlines inside strings, which is what makes the
    single-line framing safe. This pins that property.
    """
    encoded = json.dumps(blob) + "\n"
    assert encoded.count("\n") == 1

    assert _read_with_stdin(monkeypatch, encoded) == blob

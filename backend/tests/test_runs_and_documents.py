"""Phase 7 API tests: run history, artifacts, documents, per-run HITL routing.

Runs are the product's unit of history, so the endpoints must be tenant-safe
(a run belongs to its token subject), and the document store must only accept
sane files since its contents are handed to the agent subprocess.
"""

import asyncio
import io
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import server
from tests.test_server import MockCursor, auth_headers  # shared fixtures/seam


class RunsCursor(MockCursor):
    def __init__(self, fetchall_results=None, fetchone_results=None):
        super().__init__(fetchone_results=fetchone_results)
        self._fetchall_results = list(fetchall_results or [])

    def fetchall(self):
        if not self._fetchall_results:
            return []
        return self._fetchall_results.pop(0)


def _run_row(run_id="0b6ecb0a-45a1-4b8f-9a58-1c2d3e4f5a6b", status="succeeded"):
    now = datetime.now(timezone.utc)
    return (
        run_id,
        "Apply to the fixture job",
        status,
        "completed with a final response",
        "Done. Application submitted.",
        [{"index": 0, "description": "job 1", "status": "success"}],
        True,
        now,
        now,
    )


# ---------------------------------------------------------------------------
# Runs API
# ---------------------------------------------------------------------------

def test_list_runs_requires_token():
    client = TestClient(server.app)
    assert client.get('/api/runs').status_code == 401


def test_list_runs_returns_the_callers_history(monkeypatch):
    monkeypatch.setattr(server, 'cur', RunsCursor(fetchall_results=[[_run_row()]]))
    client = TestClient(server.app)
    resp = client.get('/api/runs', headers=auth_headers(1))
    assert resp.status_code == 200
    runs = resp.json()['runs']
    assert len(runs) == 1
    assert runs[0]['status'] == 'succeeded'
    assert runs[0]['has_screenshot'] is True
    assert runs[0]['item_results'][0]['status'] == 'success'
    assert runs[0]['started_at'] is not None


def test_get_run_rejects_a_non_uuid_id(monkeypatch):
    monkeypatch.setattr(server, 'cur', RunsCursor())
    client = TestClient(server.app)
    resp = client.get('/api/runs/../../etc/passwd', headers=auth_headers(1))
    assert resp.status_code == 404


def test_get_run_404_when_not_owned(monkeypatch):
    # The WHERE clause carries user_id; a row for another user comes back None.
    monkeypatch.setattr(server, 'cur', RunsCursor(fetchone_results=[None]))
    client = TestClient(server.app)
    resp = client.get(
        '/api/runs/0b6ecb0a-45a1-4b8f-9a58-1c2d3e4f5a6b', headers=auth_headers(2)
    )
    assert resp.status_code == 404


def test_get_run_includes_log_tail(monkeypatch):
    row = _run_row() + ("[STDOUT] line one",)
    monkeypatch.setattr(server, 'cur', RunsCursor(fetchone_results=[row]))
    client = TestClient(server.app)
    resp = client.get(
        '/api/runs/0b6ecb0a-45a1-4b8f-9a58-1c2d3e4f5a6b', headers=auth_headers(1)
    )
    assert resp.status_code == 200
    assert resp.json()['run']['log_tail'] == "[STDOUT] line one"


def test_run_screenshot_404_when_file_missing(monkeypatch, tmp_path):
    row = _run_row() + ("",)
    monkeypatch.setattr(server, 'cur', RunsCursor(fetchone_results=[row]))
    monkeypatch.setattr(server, 'RUN_ARTIFACTS_DIR', str(tmp_path))
    client = TestClient(server.app)
    resp = client.get(
        '/api/runs/0b6ecb0a-45a1-4b8f-9a58-1c2d3e4f5a6b/screenshot',
        headers=auth_headers(1),
    )
    assert resp.status_code == 404


def test_run_screenshot_serves_the_artifact(monkeypatch, tmp_path):
    run_id = '0b6ecb0a-45a1-4b8f-9a58-1c2d3e4f5a6b'
    row = _run_row(run_id) + ("",)
    monkeypatch.setattr(server, 'cur', RunsCursor(fetchone_results=[row]))
    monkeypatch.setattr(server, 'RUN_ARTIFACTS_DIR', str(tmp_path))
    (tmp_path / f"{run_id}.jpg").write_bytes(b"\xff\xd8fakejpeg")
    client = TestClient(server.app)
    resp = client.get(f'/api/runs/{run_id}/screenshot', headers=auth_headers(1))
    assert resp.status_code == 200
    assert resp.headers['content-type'] == 'image/jpeg'
    assert resp.content.startswith(b"\xff\xd8")


# ---------------------------------------------------------------------------
# Documents API
# ---------------------------------------------------------------------------

@pytest.fixture()
def documents_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(server, 'USER_DOCUMENTS_DIR', str(tmp_path))
    return tmp_path


def test_documents_require_token(documents_dir):
    client = TestClient(server.app)
    assert client.get('/api/documents').status_code == 401


def test_upload_rejects_unknown_type(documents_dir):
    client = TestClient(server.app)
    resp = client.post(
        '/api/documents/passport',
        headers=auth_headers(1),
        files={'file': ('r.pdf', b'%PDF-1.4', 'application/pdf')},
    )
    assert resp.status_code == 404


def test_upload_rejects_unsupported_extension(documents_dir):
    client = TestClient(server.app)
    resp = client.post(
        '/api/documents/resume',
        headers=auth_headers(1),
        files={'file': ('resume.exe', b'MZ', 'application/octet-stream')},
    )
    assert resp.status_code == 400


def test_upload_rejects_oversize_files(documents_dir):
    client = TestClient(server.app)
    big = io.BytesIO(b'a' * (server.DOCUMENT_MAX_BYTES + 1))
    resp = client.post(
        '/api/documents/resume',
        headers=auth_headers(1),
        files={'file': ('resume.pdf', big, 'application/pdf')},
    )
    assert resp.status_code == 413


def test_upload_list_replace_and_delete_roundtrip(documents_dir):
    client = TestClient(server.app)

    resp = client.post(
        '/api/documents/resume',
        headers=auth_headers(1),
        files={'file': ('resume.pdf', b'%PDF-1.4 original', 'application/pdf')},
    )
    assert resp.status_code == 200
    assert 'resume' in resp.json()['documents']

    # Replacing with a different extension drops the old file entirely.
    resp = client.post(
        '/api/documents/resume',
        headers=auth_headers(1),
        files={'file': ('resume.docx', b'PK new version', 'application/octet-stream')},
    )
    assert resp.status_code == 200
    stored = list((documents_dir / '1').iterdir())
    assert [p.name for p in stored] == ['resume.docx']

    resp = client.get('/api/documents', headers=auth_headers(1))
    assert resp.json()['documents']['resume']['filename'] == 'resume.docx'

    resp = client.delete('/api/documents/resume', headers=auth_headers(1))
    assert resp.status_code == 200
    assert resp.json()['documents'] == {}


def test_documents_are_per_user(documents_dir):
    client = TestClient(server.app)
    client.post(
        '/api/documents/resume',
        headers=auth_headers(1),
        files={'file': ('resume.pdf', b'%PDF-1.4', 'application/pdf')},
    )
    resp = client.get('/api/documents', headers=auth_headers(2))
    assert resp.json()['documents'] == {}


# ---------------------------------------------------------------------------
# Per-run HITL reply routing
# ---------------------------------------------------------------------------

def test_reply_routing_targets_the_single_accepting_run():
    key = (7, 'run-a')
    queue = asyncio.Queue()
    server.HITL_REPLY_QUEUES[key] = queue
    server.HITL_ACCEPTING[key] = True
    try:
        resolved_queue, resolved_run = server._queue_for_reply(7, None)
        assert resolved_queue is queue
        assert resolved_run == 'run-a'
    finally:
        server.HITL_REPLY_QUEUES.pop(key, None)
        server.HITL_ACCEPTING.pop(key, None)


def test_reply_routing_refuses_to_guess_between_two_runs():
    keys = [(7, 'run-a'), (7, 'run-b')]
    for key in keys:
        server.HITL_REPLY_QUEUES[key] = asyncio.Queue()
        server.HITL_ACCEPTING[key] = True
    try:
        resolved_queue, _ = server._queue_for_reply(7, None)
        assert resolved_queue is None
        # An explicit run id still resolves.
        resolved_queue, resolved_run = server._queue_for_reply(7, 'run-b')
        assert resolved_queue is server.HITL_REPLY_QUEUES[(7, 'run-b')]
        assert resolved_run == 'run-b'
    finally:
        for key in keys:
            server.HITL_REPLY_QUEUES.pop(key, None)
            server.HITL_ACCEPTING.pop(key, None)


def test_reply_routing_ignores_other_users_runs():
    key = (8, 'run-c')
    server.HITL_REPLY_QUEUES[key] = asyncio.Queue()
    server.HITL_ACCEPTING[key] = True
    try:
        resolved_queue, _ = server._queue_for_reply(7, None)
        assert resolved_queue is None
    finally:
        server.HITL_REPLY_QUEUES.pop(key, None)
        server.HITL_ACCEPTING.pop(key, None)

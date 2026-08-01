"""
WebSocket authentication tests.

Before Phase 1 of docs/IMPROVEMENT_PLAN.md, `/ws/stream/{user_id}` required no
authentication at all: any client could make the server spawn a browser
subprocess with an arbitrary prompt, and the task text plus bearer token travelled
in the query string where they landed in access logs. `/ws/chat/{client_id}`
accepted a `token` query parameter and never validated it.

These tests assert that an unauthenticated socket is closed before any agent
process is started.
"""

import os

import jwt
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import server


@pytest.fixture(autouse=True)
def token_env(monkeypatch):
    monkeypatch.setenv('TOKEN_SECRET', 'testsecret-long-enough-for-hs256-abcdef')
    yield


@pytest.fixture(autouse=True)
def never_spawn_a_process(monkeypatch):
    """Fail loudly if an unauthenticated socket ever reaches process launch."""
    def boom(*args, **kwargs):
        raise AssertionError("subprocess.Popen must not run for an unauthenticated socket")

    monkeypatch.setattr(server.subprocess, 'Popen', boom)
    yield


def make_token(user_id=1, scope=None):
    scope = server.ACCESS_SCOPE if scope is None else scope
    return jwt.encode(
        {'user_id': user_id, 'scope': scope},
        os.getenv('TOKEN_SECRET'),
        algorithm='HS256',
    )


def _expect_closed(send_frames):
    """Open /ws/stream, send the given frames, and assert the server closes it."""
    client = TestClient(server.app)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('/ws/stream') as ws:
            for frame in send_frames:
                ws.send_json(frame)
            # Any receive on a closed socket raises WebSocketDisconnect.
            ws.receive_json()


def test_stream_rejects_missing_token():
    _expect_closed([{'type': 'start', 'prompt': 'do something'}])


def test_stream_rejects_invalid_token():
    _expect_closed([{'type': 'start', 'token': 'not-a-jwt', 'prompt': 'do something'}])


def test_stream_rejects_token_signed_with_wrong_secret():
    bad = jwt.encode({'user_id': 1, 'scope': server.ACCESS_SCOPE}, 'wrong-secret', algorithm='HS256')
    _expect_closed([{'type': 'start', 'token': bad, 'prompt': 'do something'}])


def test_stream_rejects_reset_scoped_token():
    _expect_closed([
        {'type': 'start', 'token': make_token(scope=server.RESET_SCOPE), 'prompt': 'do something'}
    ])


def test_stream_rejects_wrong_first_frame_type():
    _expect_closed([{'type': 'user_hitl_reply', 'token': make_token(), 'content': 'hi'}])


def test_stream_rejects_non_json_first_frame():
    client = TestClient(server.app)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('/ws/stream') as ws:
            ws.send_text('not json at all')
            ws.receive_json()


def test_stream_rejects_authenticated_frame_with_no_prompt():
    _expect_closed([{'type': 'start', 'token': make_token()}])


def test_regression_stream_path_no_longer_takes_a_user_id():
    """The user is the token subject. A caller-supplied id in the path let anyone
    address another user's HITL queue."""
    client = TestClient(server.app)
    with pytest.raises(Exception):
        with client.websocket_connect('/ws/stream/1'):
            pass


def test_chat_rejects_missing_token():
    client = TestClient(server.app)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('/ws/chat') as ws:
            ws.send_json({'type': 'auth'})
            ws.receive_json()


def test_chat_accepts_valid_token_and_reports_when_no_agent_waiting():
    client = TestClient(server.app)
    with client.websocket_connect('/ws/chat') as ws:
        ws.send_json({'type': 'auth', 'token': make_token(42)})
        assert ws.receive_json() == {'type': 'AUTH_OK'}

        # No run in flight for this user, so the reply is reported as undeliverable
        # rather than being broadcast to every connected client.
        ws.send_json({'content': 'yes'})
        message = ws.receive_json()
        assert message['type'] == 'STATUS'
        assert 'no agent' in message['content'].lower()


def test_regression_chat_does_not_broadcast_to_other_users():
    """Every chat message used to be relayed to all connected sockets as
    'Client #N says: ...', and the dashboard rendered whatever arrived as agent
    output, so one user's text appeared in another user's transcript."""
    client = TestClient(server.app)
    with client.websocket_connect('/ws/chat') as listener:
        listener.send_json({'type': 'auth', 'token': make_token(1)})
        assert listener.receive_json() == {'type': 'AUTH_OK'}

        with client.websocket_connect('/ws/chat') as sender:
            sender.send_json({'type': 'auth', 'token': make_token(2)})
            assert sender.receive_json() == {'type': 'AUTH_OK'}
            sender.send_json({'content': 'user 2 private text'})
            # Sender gets its own status back.
            assert sender.receive_json()['type'] == 'STATUS'

        # The listener must not have received anything from user 2.
        listener.send_json({'content': 'ping'})
        received = listener.receive_json()
        assert 'user 2 private text' not in str(received)

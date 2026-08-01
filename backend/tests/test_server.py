"""
Server endpoint tests.

Phase 1 of docs/IMPROVEMENT_PLAN.md changed the auth contract: protected
endpoints now return 401 instead of 200 with an `error` string, the acting user
is always the token subject, and forgot-password is a POST. Tests named
`test_regression_*` pin a specific vulnerability closed in that phase.
"""

import os
import jwt
import pytest
from fastapi.testclient import TestClient

import server

# A valid Fernet key, fixed so encrypted output is reproducible within a run.
TEST_CREDENTIALS_KEY = 'yqE6NrPtBRhkYcYr0GLXBmvhBAr1nvVFrHb4rWGoAEg='


def _hash_pw(plain: str) -> str:
    return server.hash_password_bcrypt(plain)


class MockCursor:
    def __init__(self, fetchone_results=None):
        # fetchone_results is a list of values to return for successive fetchone() calls
        self._fetchone_results = list(fetchone_results or [])
        self.executed = []

    def execute(self, query, params=None):
        # record the query and params for debugging
        self.executed.append((query, params))

    def fetchone(self):
        if not self._fetchone_results:
            return None
        return self._fetchone_results.pop(0)


@pytest.fixture(autouse=True)
def env_and_db_monkeypatch(monkeypatch):
    monkeypatch.setenv('TOKEN_SECRET', 'testsecret-long-enough-for-hs256-abcdef')
    monkeypatch.setenv('EMAIL_ACCOUNT', 'from@example.com')
    monkeypatch.setenv('EMAIL_PASSWORD', 'password')
    monkeypatch.setenv('CREDENTIALS_KEY', TEST_CREDENTIALS_KEY)

    monkeypatch.setattr(server, 'send_forgot_password', lambda to_email, pw: None)
    # The rate limiter is process-global; keep tests independent of each other.
    server._forgot_password_attempts.clear()

    yield

    server._forgot_password_attempts.clear()


def make_token(user_id: int = 1, scope: str = server.ACCESS_SCOPE):
    secret = os.getenv('TOKEN_SECRET')
    payload = {
        'user_id': user_id,
        'username': 'u',
        'firstname': 'f',
        'lastname': 'l',
        'scope': scope,
    }
    return jwt.encode(payload, secret, algorithm='HS256')


def auth_headers(user_id: int = 1, scope: str = server.ACCESS_SCOPE):
    return {'authorization': f'Bearer {make_token(user_id, scope)}'}


# ---------------------------------------------------------------------------
# GET /api/users/
# ---------------------------------------------------------------------------

def test_get_user_success(monkeypatch):
    user_row = (1, 'user1', 'First', 'Last', 'email@example.com')
    monkeypatch.setattr(server, 'cur', MockCursor(fetchone_results=[user_row]))

    client = TestClient(server.app)
    resp = client.get('/api/users/', headers=auth_headers(1))
    assert resp.status_code == 200
    data = resp.json()
    assert data['user_id'] == 1
    assert data['username'] == 'user1'


def test_get_user_requires_token(monkeypatch):
    monkeypatch.setattr(server, 'cur', MockCursor())
    client = TestClient(server.app)
    assert client.get('/api/users/').status_code == 401


def test_regression_get_user_ignores_userid_param(monkeypatch):
    """`?userId=N` used to return any user's record with no token at all (IDOR)."""
    monkeypatch.setattr(server, 'cur', MockCursor())
    client = TestClient(server.app)

    # No token: rejected regardless of the parameter.
    assert client.get('/api/users/?userId=2').status_code == 401

    # With a token for user 1, the parameter is ignored and user 1 is queried.
    mock_cur = MockCursor(fetchone_results=[(1, 'user1', 'F', 'L', 'e@example.com')])
    monkeypatch.setattr(server, 'cur', mock_cur)
    resp = client.get('/api/users/?userId=999', headers=auth_headers(1))
    assert resp.status_code == 200
    assert resp.json()['user_id'] == 1
    assert mock_cur.executed[0][1] == ('1',)


def test_regression_reset_token_is_not_an_access_token(monkeypatch):
    """A password-reset token must not authorise ordinary endpoints."""
    monkeypatch.setattr(server, 'cur', MockCursor())
    client = TestClient(server.app)
    resp = client.get('/api/users/', headers=auth_headers(1, scope=server.RESET_SCOPE))
    assert resp.status_code == 401


def test_expired_token_rejected(monkeypatch):
    import datetime as dt
    monkeypatch.setattr(server, 'cur', MockCursor())
    payload = {
        'user_id': 1,
        'scope': server.ACCESS_SCOPE,
        'exp': dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1),
    }
    token = jwt.encode(payload, os.getenv('TOKEN_SECRET'), algorithm='HS256')
    client = TestClient(server.app)
    resp = client.get('/api/users/', headers={'authorization': f'Bearer {token}'})
    assert resp.status_code == 401
    assert 'expired' in resp.json()['detail'].lower()


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_insert_user_success(monkeypatch):
    monkeypatch.setattr(server, 'cur', MockCursor(fetchone_results=[None, (42,)]))
    client = TestClient(server.app)
    body = {
        'username': 'newuser',
        'firstname': 'New',
        'lastname': 'User',
        'email': 'new@example.com',
        'password': 'pass123'
    }
    resp = client.post('/api/users/insert/', json=body)
    assert resp.status_code == 200
    assert resp.json()['userId'] == 42


def test_insert_user_missing_fields(monkeypatch):
    monkeypatch.setattr(server, 'cur', MockCursor())
    client = TestClient(server.app)
    resp = client.post('/api/users/insert/', json={'username': 'u', 'firstname': ''})
    assert resp.status_code == 200
    assert resp.json()['error'] == 'One or More Required Fields are Missing'


def test_insert_user_existing(monkeypatch):
    monkeypatch.setattr(server, 'cur', MockCursor(fetchone_results=[(1, 'exists')]))
    client = TestClient(server.app)
    body = {
        'username': 'exists',
        'firstname': 'E',
        'lastname': 'X',
        'email': 'e@example.com',
        'password': 'p'
    }
    resp = client.post('/api/users/insert/', json=body)
    assert resp.status_code == 200
    assert resp.json()['error'] == 'Username or Email Already Exists'


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

def test_login_user_success(monkeypatch):
    user_row = (1, 'user1', 'First', 'Last', _hash_pw('pass123'), False)
    monkeypatch.setattr(server, 'cur', MockCursor(fetchone_results=[user_row]))
    client = TestClient(server.app)
    resp = client.post('/api/users/login/', json={'username': 'user1', 'password': 'pass123'})
    assert resp.status_code == 200
    data = resp.json()
    assert 'token' in data
    decoded = jwt.decode(data['token'], os.getenv('TOKEN_SECRET'), algorithms=['HS256'])
    assert decoded['scope'] == server.ACCESS_SCOPE
    assert decoded['user_id'] == 1


def test_login_user_invalid(monkeypatch):
    monkeypatch.setattr(server, 'cur', MockCursor(fetchone_results=[None]))
    client = TestClient(server.app)
    resp = client.post('/api/users/login/', json={'username': 'bad', 'password': 'bad'})
    assert resp.status_code == 200
    assert resp.json()['error'] == 'Invalid Username or Password'


def test_regression_login_header_does_not_bypass_password_check(monkeypatch):
    """A valid Authorization header used to short-circuit login and return that
    token without checking the submitted credentials. Because the frontend
    attached any stored token, a second person at the same browser could type
    anything and be logged in as the previous user."""
    wrong_password_row = (1, 'victim', 'V', 'V', _hash_pw('the-real-password'), False)
    monkeypatch.setattr(server, 'cur', MockCursor(fetchone_results=[wrong_password_row]))
    client = TestClient(server.app)

    resp = client.post(
        '/api/users/login/',
        json={'username': 'victim', 'password': 'not-the-password'},
        headers=auth_headers(1),
    )
    assert resp.status_code == 200
    assert resp.json().get('error') == 'Invalid Username or Password'
    assert 'token' not in resp.json()


def test_login_requiring_password_change_returns_scoped_reset_token(monkeypatch):
    row = (7, 'user7', 'F', 'L', _hash_pw('temp-pass'), True)
    monkeypatch.setattr(server, 'cur', MockCursor(fetchone_results=[row]))
    client = TestClient(server.app)
    resp = client.post('/api/users/login/', json={'username': 'user7', 'password': 'temp-pass'})
    assert resp.status_code == 200
    data = resp.json()
    assert data['resetRequired'] is True
    assert 'token' not in data
    decoded = jwt.decode(data['resetToken'], os.getenv('TOKEN_SECRET'), algorithms=['HS256'])
    assert decoded['scope'] == server.RESET_SCOPE
    assert decoded['user_id'] == 7


# ---------------------------------------------------------------------------
# Change password
# ---------------------------------------------------------------------------

def test_change_password_with_reset_token(monkeypatch):
    mock_cur = MockCursor(fetchone_results=[(7, 'user7', 'F', 'L')])
    monkeypatch.setattr(server, 'cur', mock_cur)
    client = TestClient(server.app)
    resp = client.post(
        '/api/users/change-password',
        json={'password': 'a-new-strong-password'},
        headers=auth_headers(7, scope=server.RESET_SCOPE),
    )
    assert resp.status_code == 200
    decoded = jwt.decode(resp.json()['token'], os.getenv('TOKEN_SECRET'), algorithms=['HS256'])
    assert decoded['scope'] == server.ACCESS_SCOPE
    # chng_pass must be cleared so the user is not trapped in the reset loop.
    assert any('chng_pass = false' in q for q, _ in mock_cur.executed)


def test_change_password_rejects_access_token(monkeypatch):
    monkeypatch.setattr(server, 'cur', MockCursor())
    client = TestClient(server.app)
    resp = client.post(
        '/api/users/change-password',
        json={'password': 'a-new-strong-password'},
        headers=auth_headers(7),
    )
    assert resp.status_code == 401


def test_change_password_rejects_short_password(monkeypatch):
    monkeypatch.setattr(server, 'cur', MockCursor())
    client = TestClient(server.app)
    resp = client.post(
        '/api/users/change-password',
        json={'password': 'short'},
        headers=auth_headers(7, scope=server.RESET_SCOPE),
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Delete / update / verify
# ---------------------------------------------------------------------------

def test_delete_user_success(monkeypatch):
    monkeypatch.setattr(server, 'cur', MockCursor(fetchone_results=[(1,)]))
    client = TestClient(server.app)
    resp = client.delete('/api/users/delete/', headers=auth_headers(1))
    assert resp.status_code == 200
    assert resp.json().get('error', '') == ''


def test_delete_user_no_token(monkeypatch):
    monkeypatch.setattr(server, 'cur', MockCursor())
    client = TestClient(server.app)
    assert client.delete('/api/users/delete/').status_code == 401


def test_update_user_success(monkeypatch):
    final_user = (1, 'userx', 'F', 'L', 'ex@example.com')
    monkeypatch.setattr(server, 'cur', MockCursor(fetchone_results=[(1,), final_user]))
    client = TestClient(server.app)
    body = {'username': 'userx', 'firstname': 'F', 'lastname': 'L', 'email': 'ex@example.com', 'password': 'newpass'}
    resp = client.post('/api/users/update/', headers=auth_headers(1), json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data['username'] == 'userx'
    assert data['passUpdated'] is True


def test_update_user_requires_token(monkeypatch):
    monkeypatch.setattr(server, 'cur', MockCursor())
    client = TestClient(server.app)
    assert client.post('/api/users/update/', json={'username': 'x'}).status_code == 401


def test_verify_user_requires_token(monkeypatch):
    monkeypatch.setattr(server, 'cur', MockCursor())
    client = TestClient(server.app)
    assert client.post('/api/users/verify/', json={'password': 'p'}).status_code == 401


def test_verify_user_success(monkeypatch):
    monkeypatch.setattr(server, 'cur', MockCursor(fetchone_results=[(_hash_pw('mypass'),)]))
    client = TestClient(server.app)
    resp = client.post('/api/users/verify/', json={'password': 'mypass'}, headers=auth_headers(1))
    assert resp.status_code == 200
    assert resp.json()['verified'] is True


# ---------------------------------------------------------------------------
# Forgot password
# ---------------------------------------------------------------------------

def test_forgot_password_success(monkeypatch):
    monkeypatch.setattr(server, 'cur', MockCursor(fetchone_results=[('user@example.com', 3)]))
    client = TestClient(server.app)
    resp = client.post('/api/users/forgot-password', json={'username': 'testuser'})
    assert resp.status_code == 200
    assert resp.json().get('error', '') == ''


def test_forgot_password_missing(monkeypatch):
    monkeypatch.setattr(server, 'cur', MockCursor())
    client = TestClient(server.app)
    resp = client.post('/api/users/forgot-password', json={})
    assert resp.status_code == 200
    assert resp.json()['error'] == 'No username or email Specified'


def test_regression_forgot_password_does_not_leak_account_existence(monkeypatch):
    """The old handler replied 'No Users Found in Database' for unknown accounts,
    which allowed enumeration. Both cases must look identical."""
    monkeypatch.setattr(server, 'cur', MockCursor(fetchone_results=[('a@example.com', 1)]))
    client = TestClient(server.app)
    existing = client.post('/api/users/forgot-password', json={'username': 'real'})

    server._forgot_password_attempts.clear()
    monkeypatch.setattr(server, 'cur', MockCursor(fetchone_results=[None]))
    missing = client.post('/api/users/forgot-password', json={'username': 'nope'})

    assert existing.status_code == missing.status_code == 200
    assert existing.json() == missing.json()


def test_regression_forgot_password_is_not_a_get(monkeypatch):
    """It used to rotate the password on a GET with the address in the query
    string, which is CSRF-able from an <img src> and logs PII."""
    monkeypatch.setattr(server, 'cur', MockCursor())
    client = TestClient(server.app)
    resp = client.get('/api/users/forgot-password/?username=victim')
    assert resp.status_code in (404, 405)


def test_forgot_password_is_rate_limited(monkeypatch):
    monkeypatch.setattr(server, 'cur', MockCursor())
    client = TestClient(server.app)
    codes = [
        client.post('/api/users/forgot-password', json={'username': f'u{i}'}).status_code
        for i in range(server._FORGOT_PASSWORD_MAX_ATTEMPTS + 2)
    ]
    assert 429 in codes


# ---------------------------------------------------------------------------
# Credential vault
# ---------------------------------------------------------------------------

def test_store_credentials_requires_token(monkeypatch):
    monkeypatch.setattr(server, 'cur', MockCursor())
    client = TestClient(server.app)
    resp = client.post('/api/users/store-credentials', json={'credentials': {'fullName': 'X'}})
    assert resp.status_code == 401


def test_regression_store_credentials_ignores_client_session_id(monkeypatch):
    """Storage used to key on a client-supplied session_id while ignoring the
    Authorization header, so anyone who learned a victim's session_id could pop
    that victim's credentials into their own agent run. Rows are now keyed to the
    token subject."""
    mock_cur = MockCursor()
    monkeypatch.setattr(server, 'cur', mock_cur)
    client = TestClient(server.app)
    resp = client.post(
        '/api/users/store-credentials',
        json={'session_id': 'someone-elses-session', 'credentials': {'fullName': 'X'}},
        headers=auth_headers(11),
    )
    assert resp.status_code == 200
    params = mock_cur.executed[0][1]
    assert params[0] == 11  # keyed to the token subject, not the session_id


def test_store_credentials_encrypts_and_strips_cvv(monkeypatch):
    mock_cur = MockCursor()
    monkeypatch.setattr(server, 'cur', mock_cur)
    client = TestClient(server.app)
    resp = client.post(
        '/api/users/store-credentials',
        json={'credentials': {
            'fullName': 'Ada Lovelace',
            'userPaymentMethods': [{'cardNumber': '4111111111111111', 'cvv': '123'}],
            'userCredentialsList': [{'serviceName': 'x', 'password': 'sup3rsecret'}],
        }},
        headers=auth_headers(5),
    )
    assert resp.status_code == 200

    stored = mock_cur.executed[0][1][1]
    raw = bytes(getattr(stored, 'adapted', stored))
    # Ciphertext, not JSON: no plaintext secret survives in the stored bytes.
    assert b'sup3rsecret' not in raw
    assert b'Ada Lovelace' not in raw
    assert b'4111111111111111' not in raw

    # And the CVV is gone even after decryption.
    decrypted = server.decrypt_credentials(raw)
    assert decrypted['fullName'] == 'Ada Lovelace'
    assert 'cvv' not in decrypted['userPaymentMethods'][0]
    assert decrypted['userPaymentMethods'][0]['cardNumber'] == '4111111111111111'


def test_read_credentials_round_trip(monkeypatch):
    payload = server.encrypt_credentials({'fullName': 'Grace'})
    monkeypatch.setattr(server, 'cur', MockCursor(fetchone_results=[(payload,)]))
    client = TestClient(server.app)
    resp = client.get('/api/users/credentials', headers=auth_headers(3))
    assert resp.status_code == 200
    assert resp.json()['credentials']['fullName'] == 'Grace'


def test_read_credentials_requires_token(monkeypatch):
    monkeypatch.setattr(server, 'cur', MockCursor())
    client = TestClient(server.app)
    assert client.get('/api/users/credentials').status_code == 401


def test_store_credentials_without_key_is_unavailable(monkeypatch):
    monkeypatch.delenv('CREDENTIALS_KEY', raising=False)
    monkeypatch.setattr(server, 'cur', MockCursor())
    client = TestClient(server.app)
    resp = client.post(
        '/api/users/store-credentials',
        json={'credentials': {'fullName': 'X'}},
        headers=auth_headers(1),
    )
    # Fails closed rather than persisting plaintext.
    assert resp.status_code == 503


def test_strip_forbidden_fields_is_recursive():
    cleaned = server.strip_forbidden_fields({
        'cvv': '123',
        'CVC2': '999',
        'security_code': '000',
        'nested': [{'cvv': '1', 'keep': 'yes'}],
        'keep': 'yes',
    })
    assert cleaned == {'nested': [{'keep': 'yes'}], 'keep': 'yes'}


# ---------------------------------------------------------------------------
# HITL and removed endpoints
# ---------------------------------------------------------------------------

def test_hitl_reply_requires_token(monkeypatch):
    monkeypatch.setattr(server, 'cur', MockCursor())
    client = TestClient(server.app)
    assert client.post('/api/hitl_reply', json={'content': 'yes'}).status_code == 401


@pytest.mark.parametrize(
    'method,path',
    [
        ('post', '/api/start_agent'),
        ('get', '/send_logs'),
        ('get', '/api/nuke'),
        ('post', '/api/hitl_reply/1'),
    ],
)
def test_regression_removed_endpoints_are_gone(monkeypatch, method, path):
    monkeypatch.setattr(server, 'cur', MockCursor())
    client = TestClient(server.app)
    kwargs = {'json': {}} if method == 'post' else {}
    resp = getattr(client, method)(path, **kwargs)
    assert resp.status_code in (404, 405)


def test_cors_is_not_wildcard():
    """`allow_origins=['*']` with `allow_credentials=True` is not a valid
    combination and defeats the check."""
    assert '*' not in server._allowed_origins()


def test_cors_origins_come_from_env(monkeypatch):
    monkeypatch.setenv('ALLOWED_ORIGINS', 'https://a.example, https://b.example')
    assert server._allowed_origins() == ['https://a.example', 'https://b.example']

import os
import jwt
import pytest
from fastapi.testclient import TestClient

import server


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
    # Set environment variables used by server
    monkeypatch.setenv('BCRYPT_SALT', '$2b$12$abcdefghijklmnopqrstuv')
    monkeypatch.setenv('TOKEN_SECRET', 'testsecret')
    monkeypatch.setenv('EMAIL_ACCOUNT', 'from@example.com')
    monkeypatch.setenv('EMAIL_PASSWORD', 'password')

    # Patch bcrypt.hashpw to return a stable value for tests
    import bcrypt as _bcrypt

    def fake_hashpw(password, salt):
        return b'hashed-' + password

    # Replace bcrypt.hashpw used inside server module
    monkeypatch.setattr(server.bcrypt, 'hashpw', fake_hashpw)

    # Patch send_forgot_password so no email is sent during tests
    monkeypatch.setattr(server, 'send_forgot_password', lambda to_email, pw: None)

    # Ensure server.cur is replaced per-test by individual tests when needed
    yield


def make_token(user_id: int = 1):
    secret = os.getenv('TOKEN_SECRET')
    payload = {'user_id': user_id, 'username': 'u', 'firstname': 'f', 'lastname': 'l'}
    return jwt.encode(payload, secret, algorithm='HS256')


def test_get_user_success(monkeypatch):
    # Prepare a cursor that will return a single user row
    user_row = (1, 'user1', 'First', 'Last', 'email@example.com', 'pw', False, False, False)
    mock_cur = MockCursor(fetchone_results=[user_row])
    monkeypatch.setattr(server, 'cur', mock_cur)

    client = TestClient(server.app)
    resp = client.get('/api/users/?userId=1')
    assert resp.status_code == 200
    data = resp.json()
    assert data['user_id'] == 1
    assert data['username'] == 'user1'


def test_get_user_missing_userid(monkeypatch):
    mock_cur = MockCursor()
    monkeypatch.setattr(server, 'cur', mock_cur)
    client = TestClient(server.app)
    resp = client.get('/api/users/')
    assert resp.status_code == 200
    assert resp.json()['error'] == 'No UserId Specified'


def test_get_user_invalid_userid(monkeypatch):
    mock_cur = MockCursor()
    monkeypatch.setattr(server, 'cur', mock_cur)
    client = TestClient(server.app)
    resp = client.get('/api/users/?userId=0')
    assert resp.status_code == 200
    assert resp.json()['error'] == 'UserId is Invalid'


def test_insert_user_success(monkeypatch):
    # Sequence: user_exists -> None (no user), then INSERT returns (newId,)
    mock_cur = MockCursor(fetchone_results=[None, (42,)])
    monkeypatch.setattr(server, 'cur', mock_cur)

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
    data = resp.json()
    assert data['userId'] == 42


def test_insert_user_missing_fields(monkeypatch):
    mock_cur = MockCursor()
    monkeypatch.setattr(server, 'cur', mock_cur)
    client = TestClient(server.app)
    body = {'username': 'u', 'firstname': ''}
    resp = client.post('/api/users/insert/', json=body)
    assert resp.status_code == 200
    assert resp.json()['error'] == 'One or More Required Fields are Missing'


def test_insert_user_existing(monkeypatch):
    # user_exists returns a non-empty row
    mock_cur = MockCursor(fetchone_results=[(1, 'exists')])
    monkeypatch.setattr(server, 'cur', mock_cur)
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


def test_login_user_success(monkeypatch):
    # login hashes password then SELECT should return a user row
    user_row = (1, 'user1', 'First', 'Last', 'email', 'pw', False, False, False)
    mock_cur = MockCursor(fetchone_results=[user_row])
    monkeypatch.setattr(server, 'cur', mock_cur)
    client = TestClient(server.app)
    body = {'username': 'user1', 'password': 'pass123'}
    resp = client.post('/api/users/login/', json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert 'token' in data


def test_login_user_invalid(monkeypatch):
    mock_cur = MockCursor(fetchone_results=[None])
    monkeypatch.setattr(server, 'cur', mock_cur)
    client = TestClient(server.app)
    body = {'username': 'bad', 'password': 'bad'}
    resp = client.post('/api/users/login/', json=body)
    assert resp.status_code == 200
    assert resp.json()['error'] == 'Invalid Username or Password'


def test_delete_user_success(monkeypatch):
    # decode token -> user_id 1, user_exists_id returns a row
    mock_cur = MockCursor(fetchone_results=[(1, 'u')])
    monkeypatch.setattr(server, 'cur', mock_cur)
    token = make_token(1)
    client = TestClient(server.app)
    headers = {'authorization': f'Bearer {token}'}
    resp = client.delete('/api/users/delete/', headers=headers)
    assert resp.status_code == 200
    assert resp.json().get('error', '') == ''


def test_delete_user_no_token(monkeypatch):
    mock_cur = MockCursor()
    monkeypatch.setattr(server, 'cur', mock_cur)
    client = TestClient(server.app)
    resp = client.delete('/api/users/delete/')
    assert resp.status_code == 200
    assert resp.json()['error'] == 'No Token Provided'


def test_update_user_success(monkeypatch):
    # token decode -> user_id, user_exists_id first, then final SELECT returns user row
    final_user = (1, 'userx', 'F', 'L', 'ex@example.com', 'pw', False, False, False)
    mock_cur = MockCursor(fetchone_results=[(1,), final_user])
    monkeypatch.setattr(server, 'cur', mock_cur)
    token = make_token(1)
    client = TestClient(server.app)
    headers = {'authorization': f'Bearer {token}'}
    body = {'username': 'userx', 'firstname': 'F', 'lastname': 'L', 'email': 'ex@example.com', 'password': 'newpass'}
    resp = client.post('/api/users/update/', headers=headers, json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data['username'] == 'userx'
    assert data['passUpdated'] is True


def test_forgot_password_success(monkeypatch):
    # when username lookup returns (email, user_id)
    mock_cur = MockCursor(fetchone_results=[('user@example.com', 3)])
    monkeypatch.setattr(server, 'cur', mock_cur)
    client = TestClient(server.app)
    resp = client.get('/api/users/forgot-password/?username=testuser')
    assert resp.status_code == 200
    assert resp.json().get('error', '') == ''


def test_forgot_password_missing(monkeypatch):
    mock_cur = MockCursor()
    monkeypatch.setattr(server, 'cur', mock_cur)
    client = TestClient(server.app)
    resp = client.get('/api/users/forgot-password/')
    assert resp.status_code == 200
    assert resp.json()['error'] == 'No username or email Specified'

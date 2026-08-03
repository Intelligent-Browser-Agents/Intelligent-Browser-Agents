"""
FastAPI application: authentication, credential vault, and agent orchestration.

Security model
--------------
Every REST endpoint except registration, login, and forgot-password requires a
bearer access token, and the acting user is always derived from that token rather
than from a request parameter. Both WebSocket endpoints authenticate with a first
frame carrying the token, so credentials never appear in a URL or an access log.

Saved user credentials live in Postgres encrypted with Fernet and keyed to the
authenticated user id. They are handed to the agent subprocess over stdin, never
as a command-line argument.
"""

# FastAPI framework, Requests for anything but GET
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from playwright.async_api import async_playwright
import socket

# ForJWT Gen
import jwt
from datetime import datetime, timezone, timedelta

# Used for Ensuring Startup and Shutdown Events
from contextlib import asynccontextmanager, contextmanager

# Database Config and Connection
import yaml
import psycopg2
from psycopg2 import pool as psycopg2_pool

# For loading .env variables
import os
from dotenv import load_dotenv

# Password hashing (import once at load time; native bcrypt + reload/re-import can misbehave)
import bcrypt

# Credential encryption at rest
from cryptography.fernet import Fernet, InvalidToken

# Emailing
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Random Password Generation
import secrets
from fastapi.middleware.cors import CORSMiddleware

# start agent endpoint
import sys
import subprocess
import threading
import uuid

import asyncio
import json
import time

# Windows requires ProactorEventLoop for asyncio subprocess support.
if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception as e:
        print(f"Warning: could not set Windows Proactor event loop policy: {e}")


# Global Variables
DB_POOL = None  # psycopg2 ThreadedConnectionPool
cur = None  # test seam only: when set, get_cursor() yields this instead of the pool
userdb_config_path = 'configs/user_db_config.yaml'
userdb_config = None
PORT_POOL = asyncio.Queue()

ACCESS_TOKEN_TTL_HOURS = 1
RESET_TOKEN_TTL_MINUTES = 15
ACCESS_SCOPE = "access"
RESET_SCOPE = "password_reset"

# Fields that must never be persisted, at any layer. Storing a card verification
# value is prohibited by PCI-DSS regardless of encryption.
FORBIDDEN_CREDENTIAL_FIELDS = frozenset({"cvv", "cvc", "cvv2", "cvc2", "securitycode", "security_code"})

_FORGOT_PASSWORD_WINDOW_SECONDS = 15 * 60
_FORGOT_PASSWORD_MAX_ATTEMPTS = 5
_forgot_password_attempts: dict[str, list[float]] = {}


def _allowed_origins() -> list[str]:
    """CORS origins from ALLOWED_ORIGINS, defaulting to the Vite dev server.

    `allow_origins=["*"]` together with `allow_credentials=True` is not a valid
    combination: browsers reject a wildcard origin on credentialed requests, and
    it defeats the purpose of the check.
    """
    raw = os.getenv("ALLOWED_ORIGINS", "")
    origins = [item.strip() for item in raw.split(",") if item.strip()]
    return origins or ["http://localhost:5173", "http://127.0.0.1:5173"]

_DB_ENV_KEYS = {
    "dbname": "DB_NAME",
    "user": "DB_USER",
    "password": "DB_PASSWORD",
    "port": "DB_PORT",
    "host": "DB_HOST",
}

_DB_DEFAULTS = {
    "dbname": "postgres",
    "user": "postgres",
    "password": "",
    "port": "5432",
    "host": "127.0.0.1",
}


def load_db_config() -> dict:
    """Resolve Postgres settings from the environment, with a local file override.

    Precedence, highest first:
      1. DB_NAME / DB_USER / DB_PASSWORD / DB_PORT / DB_HOST environment variables
      2. configs/user_db_config.yaml, if present (gitignored; local dev convenience)
      3. localhost defaults

    The YAML file used to be committed with a real password and a private VPC
    address in it. It is now gitignored, and the environment is the source of
    truth so deployments never need it on disk.
    """
    config = dict(_DB_DEFAULTS)

    try:
        with open(userdb_config_path, 'r') as file:
            from_file = yaml.safe_load(file) or {}
        if isinstance(from_file, dict):
            for key in _DB_ENV_KEYS:
                if from_file.get(key) is not None:
                    config[key] = from_file[key]
    except FileNotFoundError:
        pass
    except yaml.YAMLError as e:
        print(f"Warning: could not parse '{userdb_config_path}': {e}")

    for key, env_name in _DB_ENV_KEYS.items():
        value = os.getenv(env_name)
        if value is not None and value != "":
            config[key] = value

    return {key: str(value) for key, value in config.items()}

"""
Database access
"""


@contextmanager
def get_cursor(commit: bool = True):
    """Yield a cursor on a connection borrowed from the pool for this call only.

    Previously a single module-level connection and cursor were shared by every
    request. psycopg2 cursors are not safe for concurrent use, so overlapping
    requests could interleave results.

    When the module-level ``cur`` is set, it is yielded instead. That is the seam
    the tests use to inject a fake cursor; it is always None in production.
    """
    if cur is not None:
        yield cur
        return

    if DB_POOL is None:
        raise RuntimeError("Database pool is not initialised; did the app start up?")

    connection = DB_POOL.getconn()
    try:
        with connection.cursor() as cursor:
            yield cursor
        if commit:
            connection.commit()
        else:
            connection.rollback()
    except Exception:
        connection.rollback()
        raise
    finally:
        DB_POOL.putconn(connection)


def init_schema() -> None:
    """Create the credential vault table if it does not exist."""
    with get_cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_credentials (
                user_id INTEGER PRIMARY KEY,
                payload BYTEA NOT NULL,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
            """
        )


"""
Authentication
"""


def _token_secret() -> str:
    secret = os.getenv('TOKEN_SECRET')
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Server is missing TOKEN_SECRET; cannot issue or validate tokens.",
        )
    return secret


def create_access_token(user_id: int, username: str, firstname: str, lastname: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        'user_id': user_id,
        'username': username,
        'firstname': firstname,
        'lastname': lastname,
        'scope': ACCESS_SCOPE,
        'iat': now,
        'exp': now + timedelta(hours=ACCESS_TOKEN_TTL_HOURS),
    }
    return jwt.encode(payload, _token_secret(), algorithm='HS256')


def create_reset_token(user_id: int) -> str:
    """Short-lived token that authorises exactly one action: setting a new password."""
    now = datetime.now(timezone.utc)
    payload = {
        'user_id': user_id,
        'scope': RESET_SCOPE,
        'iat': now,
        'exp': now + timedelta(minutes=RESET_TOKEN_TTL_MINUTES),
    }
    return jwt.encode(payload, _token_secret(), algorithm='HS256')


def _bearer_token(request: Request) -> str:
    header = request.headers.get('authorization') or ''
    scheme, _, token = header.partition(' ')
    if scheme.lower() != 'bearer':
        return ''
    token = token.strip()
    # The frontend has historically stringified missing values into the header.
    if token in ('', 'undefined', 'null', 'None'):
        return ''
    return token


def _decode_scoped_token(token: str, expected_scope: str) -> dict:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        decoded = jwt.decode(token, _token_secret(), algorithms=['HS256'])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        # Deliberately not echoing the library's message back to the client.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # A reset token must never be usable as an access token, and vice versa.
    if decoded.get('scope') != expected_scope:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is not valid for this operation.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = decoded.get('user_id')
    if not isinstance(user_id, int) or user_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return decoded


async def require_user(request: Request) -> int:
    """FastAPI dependency: the authenticated user id, from the token only.

    Endpoints must never accept a caller-supplied user id. Doing so was an IDOR:
    `GET /api/users/?userId=N` returned any user's record with no token at all.
    """
    return _decode_scoped_token(_bearer_token(request), ACCESS_SCOPE)['user_id']


async def require_reset_user(request: Request) -> int:
    """FastAPI dependency: the user id from a password-reset token."""
    return _decode_scoped_token(_bearer_token(request), RESET_SCOPE)['user_id']


"""
Credential vault encryption
"""


def _fernet() -> Fernet:
    key = os.getenv('CREDENTIALS_KEY')
    if not key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Credential storage is disabled: CREDENTIALS_KEY is not set. Generate one "
                "with: python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\""
            ),
        )
    try:
        return Fernet(key.encode('utf-8') if isinstance(key, str) else key)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="CREDENTIALS_KEY is not a valid Fernet key.",
        )


def strip_forbidden_fields(value):
    """Recursively drop fields that must never be persisted (CVV and friends)."""
    if isinstance(value, dict):
        return {
            k: strip_forbidden_fields(v)
            for k, v in value.items()
            if k.strip().lower().replace('-', '_') not in FORBIDDEN_CREDENTIAL_FIELDS
        }
    if isinstance(value, list):
        return [strip_forbidden_fields(item) for item in value]
    return value


def encrypt_credentials(credentials: dict) -> bytes:
    payload = json.dumps(credentials, ensure_ascii=False, default=str).encode('utf-8')
    return _fernet().encrypt(payload)


def decrypt_credentials(payload) -> dict:
    if payload is None:
        return {}
    raw = bytes(payload) if isinstance(payload, memoryview) else payload
    try:
        decrypted = _fernet().decrypt(raw)
    except InvalidToken:
        # Wrong or rotated key. Treat as empty rather than leaking a 500.
        print("[credentials] Stored blob could not be decrypted with the current CREDENTIALS_KEY.")
        return {}
    try:
        loaded = json.loads(decrypted.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def load_user_credentials(user_id: int) -> dict:
    with get_cursor(commit=False) as cursor:
        cursor.execute('SELECT payload FROM user_credentials WHERE user_id = %s;', (user_id,))
        row = cursor.fetchone()
    if not row:
        return {}
    return decrypt_credentials(row[0])


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic: initialise the database connection pool
    global DB_POOL
    global userdb_config

    print('Loading environment variables...')
    # Do not expand $... inside values (default dotenv treats $ as variable refs).
    load_dotenv(interpolate=False)

    print("Resolving database configuration")
    userdb_config = load_db_config()

    print(
        "Connecting to the PostgreSQL database at "
        f"{userdb_config['host']}:{userdb_config['port']}/{userdb_config['dbname']}..."
    )
    DB_POOL = psycopg2_pool.ThreadedConnectionPool(
        minconn=1,
        maxconn=int(os.getenv('DB_MAX_CONNECTIONS', '10')),
        dbname=userdb_config['dbname'],
        user=userdb_config['user'],
        password=userdb_config['password'],
        port=userdb_config['port'],
        host=userdb_config['host'],
    )
    print("Database pool ready!")

    try:
        init_schema()
        print("Credential vault schema ready.")
    except Exception as exc:
        print(f"Warning: could not ensure user_credentials table exists: {exc}")

    if not os.getenv('CREDENTIALS_KEY'):
        print(
            "Warning: CREDENTIALS_KEY is not set. Credential storage endpoints will "
            "return 503 until it is configured."
        )

    while not PORT_POOL.empty():
        await PORT_POOL.get()

    for p in range(9000, 9010):  # Using 9000+
        await PORT_POOL.put(p)
    print(f"POOL READY: {PORT_POOL.qsize()} ports available.")

    yield

    print("Closing database pool...")
    if DB_POOL is not None:
        DB_POOL.closeall()
        print('Database pool closed.')

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

"""
Helper Functions
"""
def user_exists(username: str, email: str) -> bool:
    with get_cursor(commit=False) as cursor:
        cursor.execute(
            'SELECT user_id FROM users WHERE username = %s OR email = %s;',
            (username, email),
        )
        return cursor.fetchone() is not None

def user_exists_id(userId: int) -> bool:
    with get_cursor(commit=False) as cursor:
        cursor.execute('SELECT user_id FROM users WHERE user_id = %s;', (str(userId),))
        return cursor.fetchone() is not None


def hash_password_bcrypt(plain_password: str) -> str:
    """Hash a password for DB storage using a fresh salt (standard bcrypt usage)."""
    try:
        rounds = int(os.getenv("BCRYPT_ROUNDS", "12"))
    except ValueError:
        rounds = 12
    rounds = max(4, min(31, rounds))
    salt = bcrypt.gensalt(rounds=rounds)
    salt_b = salt.encode("utf-8") if isinstance(salt, str) else salt
    pw_b = (
        plain_password.encode("utf-8")
        if isinstance(plain_password, str)
        else plain_password
    )
    out = bcrypt.hashpw(pw_b, salt_b)
    return out.decode("utf-8") if isinstance(out, bytes) else out


def verify_password(plain_password: str, stored_hash: str | None) -> bool:
    """True if ``plain_password`` matches ``stored_hash`` (bcrypt hash from DB).

    Uses ``hashpw`` + constant-time compare only (no ``checkpw``). Some environments
    ship a conflicting ``bcrypt`` module without ``checkpw``; ``hashpw`` with the
    stored hash as the salt is standard and works across those builds.
    """
    if not plain_password or not stored_hash:
        return False
    try:
        pw = (
            plain_password.encode("utf-8")
            if isinstance(plain_password, str)
            else plain_password
        )
        sh = (
            stored_hash.encode("utf-8")
            if isinstance(stored_hash, str)
            else stored_hash
        )
        out = bcrypt.hashpw(pw, sh)
        out_b = out if isinstance(out, bytes) else out.encode("utf-8")
        return secrets.compare_digest(out_b, sh)
    except (ValueError, TypeError):
        return False


def send_forgot_password(to_email: str, new_password: str) -> None:
    from_email = os.getenv('EMAIL_ACCOUNT')
    from_password = os.getenv('EMAIL_PASSWORD')

    subject = "Password Reset - Intelligent Browser Agents"
    body = f"Your new password is: {new_password}\nPlease change it after logging in."

    msg = MIMEMultipart()
    msg['From'] = from_email
    msg['To'] = to_email
    msg['Subject'] = subject

    msg.attach(MIMEText(body, 'plain'))

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(from_email, from_password)
        text = msg.as_string()
        server.sendmail(from_email, to_email, text)
        server.quit()
        print(f"Password reset email sent to {to_email}")
    except Exception as e:
        print(f"Failed to send email: {e}")

"""
User CRUD Endpoints
"""
@app.get('/api/users/')  # Get the authenticated user
async def get_user(user_id: int = Depends(require_user)):
    #incoming: bearer access token
    #outgoing: username, firstname, lastname, email
    #
    # The `userId` query parameter this endpoint used to accept was an IDOR: it
    # returned any user's record with no token at all. The user is now always the
    # token subject. Columns are listed explicitly rather than using SELECT *,
    # which silently depended on physical column order.
    with get_cursor(commit=False) as cursor:
        cursor.execute(
            'SELECT user_id, username, firstname, lastname, email '
            'FROM users WHERE user_id = %s;',
            (str(user_id),),
        )
        results = cursor.fetchone()

    if results is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    return {
        'user_id': results[0],
        'username': results[1],
        'firstname': results[2],
        'lastname': results[3],
        'email': results[4],
        'error': '',
    }


@app.post('/api/users/insert/') # Insert New User 
async def insert_user(request: Request):
    #incoming: username, firstname, lastname, email, password
    #outgoing: UserId
    error  = ''
    body = await request.json()

    username = body['username'] if 'username' in body else ''
    firstname = body['firstname'] if 'firstname' in body else ''
    lastname = body['lastname'] if 'lastname' in body else ''
    email = body['email'] if 'email' in body else ''
    password = body['password'] if 'password' in body else ''

    # Checking values in query
    if username == '' or firstname == '' or lastname == '' or email == '' or password == '':
        error = 'One or More Required Fields are Missing'
        return {'error' : error}
    
    # Check if the user already exists
    check = user_exists(username, email)
    if check is True:
        error = 'Username or Email Already Exists'
        return {'error' : error}
    
    # Inserting the new user
    query = 'INSERT INTO users (username, firstname, lastname, email, isverified, chng_pass, password) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING user_id;'
    hashed_password = hash_password_bcrypt(password)
    with get_cursor() as cursor:
        cursor.execute(query, (username, firstname, lastname, email, False, False, hashed_password))
        newUserId = cursor.fetchone()[0]
    return {'userId': newUserId, 'error': error}

@app.delete('/api/users/delete/') # Delete the authenticated user
async def delete_user(user_id: int = Depends(require_user)):
    #incoming: bearer access token
    #outgoing: success/failure
    #
    # The old handler returned `{'error': e}` with a raw exception object on an
    # invalid token, which FastAPI cannot serialise, producing a 500.
    if not user_exists_id(user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    with get_cursor() as cursor:
        # Remove the credential vault row first; there is no FK to cascade from.
        cursor.execute('DELETE FROM user_credentials WHERE user_id = %s;', (user_id,))
        cursor.execute('DELETE FROM users WHERE user_id = %s;', (str(user_id),))

    return {'error': ''}

@app.post('/api/users/update/') # Update the authenticated user's info
async def update_user(request: Request, user_id: int = Depends(require_user)):
    #incoming: bearer access token, any of username/firstname/lastname/email/password
    #outgoing: new user info
    pass_updated = False
    body = await request.json()

    username = body['username'] if 'username' in body else None
    firstname = body['firstname'] if 'firstname' in body else None
    lastname = body['lastname'] if 'lastname' in body else None
    email = body['email'] if 'email' in body else None
    password = body['password'] if 'password' in body else None

    if not user_exists_id(user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    # One connection for the whole update so a partial failure rolls back together,
    # instead of each field being its own autocommitted statement.
    with get_cursor() as cursor:
        if username is not None:
            cursor.execute('UPDATE users SET username = %s WHERE user_id = %s;', (username, str(user_id)))
        if firstname is not None:
            cursor.execute('UPDATE users SET firstname = %s WHERE user_id = %s;', (firstname, str(user_id)))
        if lastname is not None:
            cursor.execute('UPDATE users SET lastname = %s WHERE user_id = %s;', (lastname, str(user_id)))
        if email is not None:
            cursor.execute('UPDATE users SET email = %s WHERE user_id = %s;', (email, str(user_id)))
        if password is not None:
            hashed_password = hash_password_bcrypt(password)
            cursor.execute(
                'UPDATE users SET password = %s, chng_pass = false WHERE user_id = %s;',
                (hashed_password, str(user_id)),
            )
            pass_updated = True

        cursor.execute(
            'SELECT user_id, username, firstname, lastname, email '
            'FROM users WHERE user_id = %s;',
            (str(user_id),),
        )
        results = cursor.fetchone()

    if results is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    return {
        'user_id': results[0],
        'username': results[1],
        'firstname': results[2],
        'lastname': results[3],
        'email': results[4],
        'passUpdated': pass_updated,
        'error': '',
    }


@app.post('/api/users/login/') # User Login
async def login_user(request: Request):
    #incoming: username, password
    #outgoing: token, or a scoped reset token when a password change is required
    #
    # This endpoint used to short-circuit on a valid Authorization header and
    # return that token without checking the submitted credentials at all. Because
    # the frontend attached any stored token to the login request, a second person
    # at the same browser could type arbitrary credentials and be logged in as the
    # previous user. The header is now ignored entirely: logging in requires proving
    # the password.
    body = await request.json()

    username = body.get('username') or ''
    password = body.get('password') or ''

    if username == '' or password == '':
        return {'error': 'Username or Password is Missing'}

    with get_cursor(commit=False) as cursor:
        cursor.execute(
            "SELECT user_id, username, firstname, lastname, password, chng_pass "
            "FROM users WHERE username = %s;",
            (username,),
        )
        results = cursor.fetchone()

    if results is None or not verify_password(password, results[4]):
        # Identical response for "no such user" and "wrong password".
        return {'error': 'Invalid Username or Password'}

    user_id, db_username, firstname, lastname, _stored_hash, chng_pass = results

    if chng_pass:
        # Hand back a token scoped to the password-change endpoint only. Previously
        # a full access token was returned alongside error='Password Change
        # Required', which the frontend then discarded, leaving the reset flow with
        # no way to complete.
        return {
            'resetRequired': True,
            'resetToken': create_reset_token(user_id),
            'error': 'Password Change Required',
        }

    return {
        'token': create_access_token(user_id, db_username, firstname, lastname),
        'error': '',
    }

@app.post('/api/users/verify/') # Confirm the authenticated user's password
async def verify_user(request: Request, user_id: int = Depends(require_user)):
    body = await request.json()
    password = body.get('password') or ''

    if password == '':
        return {'verified': False, 'error': 'Password is Missing'}

    with get_cursor(commit=False) as cursor:
        cursor.execute("SELECT password FROM users WHERE user_id = %s;", (str(user_id),))
        result = cursor.fetchone()

    if result is None or not verify_password(password, result[0]):
        return {'verified': False, 'error': 'Invalid password'}

    return {'verified': True, 'error': ''}


def _forgot_password_rate_limited(client_key: str) -> bool:
    """Crude in-process sliding window. Enough to stop trivial enumeration loops."""
    now = time.monotonic()
    attempts = [
        ts for ts in _forgot_password_attempts.get(client_key, [])
        if now - ts < _FORGOT_PASSWORD_WINDOW_SECONDS
    ]
    if len(attempts) >= _FORGOT_PASSWORD_MAX_ATTEMPTS:
        _forgot_password_attempts[client_key] = attempts
        return True
    attempts.append(now)
    _forgot_password_attempts[client_key] = attempts
    return False


@app.post('/api/users/forgot-password') # User Forgot Password
async def forgot_password(request: Request):
    #incoming: {"username": ...} or {"email": ...}
    #outgoing: always the same response
    #
    # Was a GET that rotated the user's password with the address in the query
    # string. That made it CSRF-able from any <img src>, put PII in access logs,
    # and its distinct "No Users Found in Database" reply allowed account
    # enumeration. It is now a POST with a single generic response.
    body = await request.json()
    username = body.get('username') or None
    email = body.get('email') or None

    if not username and not email:
        return {'error': 'No username or email Specified'}

    client_host = request.client.host if request.client else 'unknown'
    if _forgot_password_rate_limited(client_host):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many password reset requests. Try again later.",
        )

    if username:
        query = 'SELECT email, user_id FROM users WHERE username = %s;'
        params = (username,)
    else:
        query = 'SELECT email, user_id FROM users WHERE email = %s;'
        params = (email,)

    with get_cursor() as cursor:
        cursor.execute(query, params)
        results = cursor.fetchone()

        if results is not None:
            target_email, userId = results[0], results[1]
            new_password = secrets.token_urlsafe(12)
            hashed_password = hash_password_bcrypt(new_password)
            cursor.execute(
                'UPDATE users SET password = %s, chng_pass = true WHERE user_id = %s;',
                (hashed_password, str(userId)),
            )
            send_forgot_password(target_email, new_password)

    # Same reply whether or not the account exists.
    return {'error': ''}


@app.post('/api/users/change-password') # Complete a required password change
async def change_password(request: Request, user_id: int = Depends(require_reset_user)):
    #incoming: password-reset scoped token, {"password": "<new password>"}
    #outgoing: a normal access token
    #
    # Completes the flow that previously dead-ended: login set chng_pass, the
    # frontend discarded the token, and no change-password endpoint or page existed.
    body = await request.json()
    new_password = body.get('password') or ''

    if len(new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be at least 8 characters.",
        )

    with get_cursor() as cursor:
        cursor.execute(
            'UPDATE users SET password = %s, chng_pass = false WHERE user_id = %s;',
            (hash_password_bcrypt(new_password), str(user_id)),
        )
        cursor.execute(
            'SELECT user_id, username, firstname, lastname FROM users WHERE user_id = %s;',
            (str(user_id),),
        )
        row = cursor.fetchone()

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    return {
        'token': create_access_token(row[0], row[1], row[2], row[3]),
        'error': '',
    }


"""
Agent API Endpoints

Removed in Phase 1:
  POST /api/start_agent  broken (launched src/app.py with an unsupported
                         --video_port, and blocked the event loop with a
                         synchronous subprocess.run). Runs start over
                         WS /ws/stream instead.
  GET  /send_logs        stub whose body was `pass`.
  GET  /api/nuke         unauthenticated gc.collect() debugging leftover.
"""


@app.post('/api/users/store-credentials')
async def store_credentials(request: Request, user_id: int = Depends(require_user)):
    """Persist the caller's credential vault, encrypted, keyed to their token.

    Previously this accepted an `Authorization` header and never read it, keying
    instead on a client-supplied `session_id`. Anyone who learned a victim's
    session_id could open a stream with it and pop that victim's credential blob
    into their own agent run.
    """
    body = await request.json()
    credentials = body.get("credentials", {})
    if not isinstance(credentials, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="credentials must be an object.")

    # Drop CVV-like fields before they can reach storage.
    sanitized = strip_forbidden_fields(credentials)
    payload = encrypt_credentials(sanitized)

    with get_cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO user_credentials (user_id, payload, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (user_id) DO UPDATE
                SET payload = EXCLUDED.payload, updated_at = NOW();
            """,
            (user_id, psycopg2.Binary(payload)),
        )

    return {"ok": True, "error": ""}


@app.get('/api/users/credentials')
async def read_credentials(user_id: int = Depends(require_user)):
    """Return the caller's saved credentials so the UI can edit them.

    This replaces keeping third-party passwords and card numbers in localStorage.
    """
    return {"credentials": load_user_credentials(user_id), "error": ""}


@app.delete('/api/users/credentials')
async def delete_credentials(user_id: int = Depends(require_user)):
    with get_cursor() as cursor:
        cursor.execute('DELETE FROM user_credentials WHERE user_id = %s;', (user_id,))
    return {"ok": True, "error": ""}


async def wait_for_port(port: int, timeout: float = 10.0):
    """Poll a loopback port until something accepts a connection."""
    loop = asyncio.get_running_loop()
    start_time = loop.time()
    while loop.time() - start_time < timeout:
        try:
            probe = await loop.run_in_executor(
                None, lambda: socket.create_connection(("127.0.0.1", port), timeout=0.5)
            )
            probe.close()
            return True
        except OSError:
            # A bare `except:` here also swallowed KeyboardInterrupt and
            # SystemExit, so the loop could not be cancelled during startup.
            await asyncio.sleep(0.5)
    return False


class StreamViewUnavailable(RuntimeError):
    """The agent's browser could not be attached for the live view.

    The agent itself is unaffected and keeps running; only the video feed is lost.
    """


async def attach_to_agent_page(playwright, port: int, timeout: float = 20.0):
    """Attach over CDP once the agent has actually opened its page.

    The debugging port accepts connections as soon as Chromium boots, which is
    before `src/app.py` calls `new_context()` / `new_page()`. Attaching on the
    first successful TCP connect therefore raced the agent: Chromium reports one
    context with zero pages, so `browser.contexts[0].pages[0]` raised
    `IndexError: list index out of range` and the run lost its live view for the
    rest of the session.

    Retries until some context has a page.

    Returns (browser, context, page), or (None, None, None) if it never appears.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    last_error = "no context with a page appeared"

    while loop.time() < deadline:
        browser = None
        try:
            browser = await playwright.chromium.connect_over_cdp(f"http://localhost:{port}")
        except Exception as exc:
            last_error = f"connect_over_cdp failed: {type(exc).__name__}"
            await asyncio.sleep(0.25)
            continue

        for context in browser.contexts:
            if context.pages:
                return browser, context, context.pages[0]

        # Connected, but the page does not exist yet. Drop this connection and
        # retry rather than indexing into an empty list.
        try:
            await browser.close()
        except Exception:
            pass
        await asyncio.sleep(0.25)

    print(f"[STREAM] Could not attach to the agent browser on port {port}: {last_error}")
    return None, None, None


HITL_PREFIX = "@@HITL@@"

import json as _json

# Shared map: authenticated user_id → asyncio.Queue for HITL replies.
# Keyed by the token subject, not by a client-supplied path parameter. The
# frontend used to hash a browser-generated UUID into a fake "user_id", which
# both collided across users and reset on every page reload.
HITL_REPLY_QUEUES: dict[int, asyncio.Queue] = {}
# True only while we have sent CLARIFICATION and are waiting for stdin reply (user only).
HITL_ACCEPTING: dict[int, bool] = {}

USER_HITL_REPLY_TYPE = "user_hitl_reply"
ABORT_RUN_TYPE = "abort_run"

# How long a socket may stay open before sending its authentication frame.
WS_AUTH_TIMEOUT_SECONDS = 10


def _is_stop_command(text: str) -> bool:
    value = (text or "").strip().lower()
    return value in {"stop", "cancel", "quit", "exit", "abort"}


def _drain_async_queue(q: asyncio.Queue) -> None:
    while True:
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            break


async def _authenticate_websocket(websocket: WebSocket, expected_type: str) -> dict | None:
    """Read and validate the first frame of a WebSocket connection.

    Returns the decoded frame with an added ``user_id``, or None after closing the
    socket. Tokens travel in the frame body rather than the query string, which
    keeps them out of proxy and uvicorn access logs.
    """
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=WS_AUTH_TIMEOUT_SECONDS)
    except (asyncio.TimeoutError, WebSocketDisconnect, RuntimeError):
        await _close_websocket(websocket, code=1008, reason="Authentication frame not received")
        return None

    try:
        frame = _json.loads(raw)
    except _json.JSONDecodeError:
        await _close_websocket(websocket, code=1008, reason="Malformed authentication frame")
        return None

    if not isinstance(frame, dict) or frame.get("type") != expected_type:
        await _close_websocket(websocket, code=1008, reason="Expected an authentication frame")
        return None

    token = frame.get("token") or ""
    try:
        decoded = _decode_scoped_token(token if isinstance(token, str) else "", ACCESS_SCOPE)
    except HTTPException:
        await _close_websocket(websocket, code=1008, reason="Authentication failed")
        return None

    frame["user_id"] = decoded["user_id"]
    return frame


async def _close_websocket(websocket: WebSocket, code: int, reason: str) -> None:
    try:
        await websocket.close(code=code, reason=reason)
    except Exception:
        pass


async def _wait_for_process_or_disconnect(
    process: subprocess.Popen,
    disconnect_event: asyncio.Event,
    poll_interval: float = 0.2,
) -> None:
    """Wait for process exit, but stop waiting as soon as the socket disconnects."""
    while process.poll() is None:
        if disconnect_event.is_set():
            return
        await asyncio.sleep(poll_interval)


async def _terminate_process_gracefully(
    process: subprocess.Popen,
    timeout_seconds: float = 5.0,
) -> None:
    """Terminate a subprocess and force-kill if it does not exit in time."""
    if process.poll() is not None:
        return

    try:
        process.terminate()
    except Exception:
        return

    try:
        await asyncio.wait_for(asyncio.to_thread(process.wait), timeout=timeout_seconds)
        return
    except asyncio.TimeoutError:
        pass
    except Exception:
        return

    try:
        process.kill()
    except Exception:
        return

    try:
        await asyncio.to_thread(process.wait)
    except Exception:
        pass


@app.post("/api/hitl_reply")
async def hitl_reply(request: Request, user_id: int = Depends(require_user)):
    """REST endpoint the frontend can call to answer a clarification request.

    The user id comes from the token. It used to be a path parameter, so any
    caller could answer any running agent's clarification prompt.
    """
    if not HITL_ACCEPTING.get(user_id):
        return {"status": "error", "message": "No active clarification for this user."}
    body = await request.json()
    user_input = body.get("content", body.get("user_input", ""))
    queue = HITL_REPLY_QUEUES.get(user_id)
    if queue is None:
        return {"status": "error", "message": "No agent is waiting for input for this user."}
    await queue.put({"content": user_input})
    return {"status": "ok"}

async def _switch_to_new_page(new_page, start_screencast_fn):
    """Wait for a popup/new-tab page to load, then switch screencast to it."""
    try:
        await new_page.wait_for_load_state("domcontentloaded", timeout=10000)
        await start_screencast_fn(new_page)
    except Exception as exc:
        print(f"[screencast] Failed to switch to new tab: {exc}")


@app.websocket("/ws/stream")
async def stream_endpoint(websocket: WebSocket):
    """Run an agent task and stream logs, HITL prompts, and browser frames.

    The first frame must be {"type": "start", "token": ..., "prompt": ...}. The
    prompt and token used to arrive as query parameters, which put both the task
    text and the bearer token into every access log along the way, and the
    endpoint required no authentication at all: any client could make the server
    spawn a browser subprocess with an arbitrary prompt.
    """
    await websocket.accept()

    start_frame = await _authenticate_websocket(websocket, expected_type="start")
    if start_frame is None:
        return

    user_id: int = start_frame["user_id"]
    prompt = start_frame.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        await _close_websocket(websocket, code=1008, reason="Missing prompt")
        return

    stream_disconnect_event = asyncio.Event()

    # Credentials come from the caller's own encrypted vault row. Nothing is read
    # from a client-supplied session id.
    try:
        credentials = await asyncio.to_thread(load_user_credentials, user_id)
    except HTTPException as exc:
        # CREDENTIALS_KEY missing or invalid: run without saved credentials rather
        # than failing the whole task.
        print(f"[STREAM] Credential vault unavailable: {exc.detail}")
        credentials = {}
    except Exception as exc:
        print(f"[STREAM] Could not load credentials: {type(exc).__name__}")
        credentials = {}

    # Never log the blob itself.
    print(f"[STREAM] user_id={user_id} credential_keys={sorted(credentials.keys())}")

    port = await PORT_POOL.get()

    # A fresh identity per run, and a stable identity per user for browser
    # session (storage_state) reuse across runs. Sending run_id to the client
    # up front is what a future "resume this run" endpoint would key on; today
    # nothing consumes it yet beyond appearing in the stream.
    run_id = str(uuid.uuid4())
    await websocket.send_json({"type": "run_started", "run_id": run_id})

    current_env = os.environ.copy()
    current_env["PYTHONUNBUFFERED"] = "1"
    current_env["PYTHONIOENCODING"] = "utf-8"
    python_path = sys.executable
    loop = asyncio.get_running_loop()

    # 1. Launch Agent with stdin pipe for credentials and HITL replies
    def start_process():
        return subprocess.Popen(
            [
                python_path, "src/app.py",
                "--port", str(port),
                "--prompt", prompt,
                "--run_id", run_id,
                "--session_key", str(user_id),
            ],
            env=current_env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
    process = await loop.run_in_executor(None, start_process)

    # 2. Hand over credentials as the first stdin line. They used to be passed as
    #    a --credentials_json command-line argument, which is readable by any
    #    other process on the machine via the process list.
    #
    #    The agent blocks on this line at startup, so on a write failure we must
    #    close stdin. That gives the child EOF, and it continues without saved
    #    credentials instead of hanging until the socket drops.
    try:
        process.stdin.write((json.dumps(credentials) + "\n").encode("utf-8"))
        process.stdin.flush()
    except Exception as exc:
        print(f"[STREAM] Failed to send credentials to agent: {type(exc).__name__}")
        try:
            process.stdin.close()
        except Exception:
            pass

    # 3. Feed stdout/stderr into asyncio queue via threads
    log_queue = asyncio.Queue()

    def pipe_reader(pipe, log_type):
        try:
            for line in iter(pipe.readline, b""):
                line_str = line.decode("utf-8", errors="replace").strip()
                if line_str:
                    loop.call_soon_threadsafe(log_queue.put_nowait, (log_type, line_str))
        except Exception:
            pass
        loop.call_soon_threadsafe(log_queue.put_nowait, (f"{log_type}_DONE", None))

    threading.Thread(target=pipe_reader, args=(process.stdout, "STDOUT"), daemon=True).start()
    threading.Thread(target=pipe_reader, args=(process.stderr, "STDERR"), daemon=True).start()

    # Register a shared reply queue so any endpoint can push replies
    reply_queue = asyncio.Queue()
    HITL_REPLY_QUEUES[user_id] = reply_queue
    HITL_ACCEPTING[user_id] = False

    # Mutable ref so the listener can dispatch CDP input events once the
    # session is established (set after browser connects).
    cdp_session_ref = {"client": None}

    async def _dispatch_cdp_input(msg: dict):
        """Forward a browser input event from the frontend to the CDP session."""
        client = cdp_session_ref.get("client")
        if client is None:
            return
        try:
            input_type = msg.get("inputType")  # "mouse" or "key"
            if input_type == "mouse":
                await client.send("Input.dispatchMouseEvent", {
                    "type": msg.get("action", "mousePressed"),
                    "x": msg.get("x", 0),
                    "y": msg.get("y", 0),
                    "button": msg.get("button", "left"),
                    "clickCount": msg.get("clickCount", 1),
                })
            elif input_type == "key":
                action = msg.get("action", "keyDown")
                key = msg.get("key", "")
                code = msg.get("code", "")
                key_code = msg.get("keyCode", 0)
                modifiers = msg.get("modifiers", 0)

                params = {
                    "type": action,
                    "key": key,
                    "code": code,
                    "windowsVirtualKeyCode": key_code,
                    "nativeVirtualKeyCode": key_code,
                    "modifiers": modifiers,
                }
                if action == "char":
                    params["text"] = msg.get("text", key)
                    params["unmodifiedText"] = msg.get("unmodifiedText", key)
                elif action in ("keyDown", "rawKeyDown"):
                    params["text"] = msg.get("text", "")

                await client.send("Input.dispatchKeyEvent", params)
            elif input_type == "scroll":
                await client.send("Input.dispatchMouseEvent", {
                    "type": "mouseWheel",
                    "x": msg.get("x", 0),
                    "y": msg.get("y", 0),
                    "deltaX": msg.get("deltaX", 0),
                    "deltaY": msg.get("deltaY", 0),
                })
        except Exception as e:
            print(f"[INPUT] CDP dispatch error: {e}")

    # ── Listener: reads messages the frontend sends back through this WebSocket ──
    async def ws_reply_listener():
        try:
            while True:
                try:
                    text_data = await websocket.receive_text()
                except WebSocketDisconnect:
                    stream_disconnect_event.set()
                    break
                except Exception:
                    stream_disconnect_event.set()
                    continue
                try:
                    msg = _json.loads(text_data)
                except _json.JSONDecodeError:
                    # Non-JSON payloads are not HITL (avoids misfires / partial frames).
                    continue

                if msg.get("type") == "INPUT":
                    await _dispatch_cdp_input(msg)
                    continue

                if msg.get("type") in {USER_HITL_REPLY_TYPE, ABORT_RUN_TYPE}:
                    content = msg.get("content", "")
                    if isinstance(content, str) and _is_stop_command(content):
                        print("[HITL] Stop requested via WebSocket")
                        HITL_ACCEPTING[user_id] = False
                        _drain_async_queue(reply_queue)
                        try:
                            await websocket.send_json({
                                "type": "STATUS",
                                "content": "Abort requested. Stopping agent...",
                            })
                        except Exception:
                            pass
                        try:
                            if process.returncode is None:
                                process.terminate()
                        except Exception as exc:
                            print(f"[HITL] Failed to terminate process: {exc}")
                        continue

                # Only explicit user HITL replies while a clarification is active.
                if (
                    msg.get("type") == USER_HITL_REPLY_TYPE
                    and HITL_ACCEPTING.get(user_id)
                ):
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        # A clarification reply can legitimately contain a secret
                        # (an MFA code, a password). Log its shape, not its value.
                        print(f"[HITL] Received user_hitl_reply ({len(content)} chars)")
                        await reply_queue.put({"content": content})
                # Other message types are ignored for HITL (no queue).
        except Exception:
            stream_disconnect_event.set()
            pass

    reply_listener_task = asyncio.create_task(ws_reply_listener())

    # ── HITL-aware log consumer ──
    async def log_consumer():
        done_stdout, done_stderr = False, False
        while not (done_stdout and done_stderr):
            try:
                log_type, content = await asyncio.wait_for(log_queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            if content is None:
                if log_type == "STDOUT_DONE":
                    done_stdout = True
                elif log_type == "STDERR_DONE":
                    done_stderr = True
                continue

            # Check for HITL messages from the subprocess
            if log_type == "STDOUT" and content.startswith(HITL_PREFIX):
                raw_json = content[len(HITL_PREFIX):]
                try:
                    hitl_payload = _json.loads(raw_json)
                except _json.JSONDecodeError:
                    hitl_payload = {"type": "finish", "message": raw_json}

                hitl_type = hitl_payload.get("type", "finish")
                hitl_message = hitl_payload.get("message", "")

                try:
                    if hitl_type == "finish":
                        print(f"[HITL] Sending final response to frontend")
                        await websocket.send_json({
                            "type": "RESPONSE",
                            "content": hitl_message,
                        })
                        await websocket.send_json({
                            "type": "LOG",
                            "source": "AGENT",
                            "content": hitl_message,
                        })
                    else:
                        print(f"[HITL] Sending clarification request to frontend")
                        _drain_async_queue(reply_queue)
                        HITL_ACCEPTING[user_id] = True
                        try:
                            await websocket.send_json({
                                "type": "CLARIFICATION",
                                "message": hitl_message,
                                "requested_fields": hitl_payload.get("requested_fields", []),
                            })
                            await websocket.send_json({
                                "type": "LOG",
                                "source": "AGENT",
                                "content": f"[NEEDS INPUT] {hitl_message}",
                            })

                            print(f"[HITL] Waiting for user reply (user_id={user_id})…")
                            try:
                                ws_msg = await asyncio.wait_for(reply_queue.get(), timeout=300)
                                user_input = ws_msg.get("content", ws_msg.get("user_input", ""))
                                if not isinstance(user_input, str):
                                    user_input = str(user_input) if user_input is not None else ""
                                print(f"[HITL] Got reply ({len(str(user_input))} chars)")
                            except asyncio.TimeoutError:
                                user_input = ""
                                print("[HITL] Timed out waiting for reply")

                            reply_line = _json.dumps({"user_input": user_input}) + "\n"
                            try:
                                process.stdin.write(reply_line.encode("utf-8"))
                                process.stdin.flush()
                                print(f"[HITL] Wrote reply to subprocess stdin")
                            except Exception as exc:
                                print(f"[HITL] Failed to write to stdin: {exc}")
                                break
                        finally:
                            HITL_ACCEPTING[user_id] = False
                except Exception:
                    break
                continue

            # Regular log line
            print(f"[{log_type}] {content}")
            try:
                await websocket.send_json({"type": "LOG", "source": log_type, "content": content})
            except Exception:
                stream_disconnect_event.set()
                break

    log_task = asyncio.create_task(log_consumer())

    try:
        # 3. Wait for Browser
        await websocket.send_json({"type": "STATUS", "content": "Warming up browser..."})
        if await wait_for_port(port):
            try:
                async with async_playwright() as p:
                    browser, context, page = await attach_to_agent_page(p, port)
                    if page is None:
                        raise StreamViewUnavailable()
                    client = await context.new_cdp_session(page)
                    cdp_session_ref["client"] = client

                    async def on_frame(payload):
                        cur_client = cdp_session_ref.get("client")
                        try:
                            await websocket.send_json({"type": "FRAME", "data": payload['data']})
                            await cur_client.send("Page.screencastFrameAck", {"sessionId": payload['sessionId']})
                        except Exception:
                            stream_disconnect_event.set()

                    async def start_screencast_on(target_page):
                        """Switch screencast + CDP input to a new page."""
                        old_client = cdp_session_ref.get("client")
                        if old_client:
                            try:
                                await old_client.send("Page.stopScreencast")
                            except Exception:
                                pass
                        new_client = await context.new_cdp_session(target_page)
                        cdp_session_ref["client"] = new_client
                        new_client.on("Page.screencastFrame", on_frame)
                        await new_client.send("Page.startScreencast", {"format": "jpeg", "quality": 40})

                    client.on("Page.screencastFrame", on_frame)
                    await client.send("Page.startScreencast", {"format": "jpeg", "quality": 40})

                    context.on("page", lambda new_page: asyncio.ensure_future(
                        _switch_to_new_page(new_page, start_screencast_on)
                    ))

                    await _wait_for_process_or_disconnect(process, stream_disconnect_event)
            except StreamViewUnavailable:
                # The agent is fine; only the live view failed. Keep the socket open
                # so logs and HITL prompts still reach the user.
                try:
                    await websocket.send_json({
                        "type": "STATUS",
                        "content": "Live browser view unavailable; the agent is still running.",
                    })
                except Exception:
                    pass
                await _wait_for_process_or_disconnect(process, stream_disconnect_event)
            except NotImplementedError:
                await websocket.send_json({
                    "type": "STATUS",
                    "content": "Video streaming not available on this platform; continuing with logs only.",
                })
                await _wait_for_process_or_disconnect(process, stream_disconnect_event)
            except Exception as exc:
                print(f"[STREAM] Browser/screencast error: {exc}")
                try:
                    await websocket.send_json({
                        "type": "STATUS",
                        "content": "Browser video disconnected; agent still running.",
                    })
                except Exception:
                    pass
                await _wait_for_process_or_disconnect(process, stream_disconnect_event)
        else:
            # The debugging port never opened. Previously this fell straight through
            # to cleanup, which closed the socket and killed a perfectly healthy
            # agent run. Keep streaming logs and HITL prompts instead.
            print(f"[STREAM] Debug port {port} never opened; continuing without the live view.")
            await websocket.send_json({
                "type": "STATUS",
                "content": "Live browser view unavailable; the agent is still running.",
            })
            await _wait_for_process_or_disconnect(process, stream_disconnect_event)

    finally:
        # 5. Cleanup
        exit_reason = (
            "agent process exited" if process.poll() is not None
            else "client disconnected" if stream_disconnect_event.is_set()
            else "handler returned"
        )
        print(f"[STREAM] Run finished for user_id={user_id}: {exit_reason} (exit code {process.poll()}).")

        stream_disconnect_event.set()
        HITL_REPLY_QUEUES.pop(user_id, None)
        HITL_ACCEPTING.pop(user_id, None)

        reply_listener_task.cancel()
        try:
            await reply_listener_task
        except (asyncio.CancelledError, Exception):
            pass

        try:
            await asyncio.wait_for(log_task, timeout=3.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            log_task.cancel()
            try:
                await log_task
            except asyncio.CancelledError:
                pass

        try:
            await websocket.send_json({"type": "STATUS", "content": "Agent finished task."})
        except Exception:
            pass
        # Client cleanup (live view, isAgentRunning) runs on socket onclose; must close the socket.
        try:
            await websocket.close()
        except Exception:
            pass

        await _terminate_process_gracefully(process)
        await PORT_POOL.put(port)

@app.websocket("/ws/chat")
async def websocket_endpoint(websocket: WebSocket):
    """Fallback channel for delivering a HITL reply when no stream socket is open.

    Two changes from the previous version. It authenticates with a first frame
    instead of accepting an unvalidated `token` query parameter, and it no longer
    broadcasts. Every message used to be relayed to *every* connected socket as
    `Client #N says: ...`, and the dashboard rendered whatever arrived as agent
    output, so one user's text appeared in another user's transcript.
    """
    await websocket.accept()

    auth_frame = await _authenticate_websocket(websocket, expected_type="auth")
    if auth_frame is None:
        return

    user_id: int = auth_frame["user_id"]
    try:
        await websocket.send_json({"type": "AUTH_OK"})
    except Exception:
        return

    try:
        while True:
            data = await websocket.receive_text()

            queue = HITL_REPLY_QUEUES.get(user_id)
            if queue is None:
                try:
                    await websocket.send_json({
                        "type": "STATUS",
                        "content": "No agent is currently waiting for input.",
                    })
                except Exception:
                    break
                continue

            try:
                payload = _json.loads(data)
            except (ValueError, TypeError):
                payload = {"content": data}
            if not isinstance(payload, dict):
                payload = {"content": str(payload)}
            await queue.put(payload)
            print(f"[HITL] Forwarded chat message to agent for user {user_id}")
    except WebSocketDisconnect:
        pass
    finally:
        await _close_websocket(websocket, code=1000, reason="closed")

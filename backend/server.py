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
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect, status
from fastapi.responses import FileResponse
from cdp_stream import ScreencastRelay

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
from collections import deque

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
    """Create the credential vault and runs tables if they do not exist."""
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
        # Runs are the product's unit of history: what was asked, how it
        # ended, what it answered, and per-item outcomes for bulk missions.
        # Full log transcripts stay out of the database; log_tail is for
        # diagnosis and the screenshot artifact carries the visual evidence.
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id UUID PRIMARY KEY,
                user_id INTEGER NOT NULL,
                prompt TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                exit_reason TEXT NOT NULL DEFAULT '',
                final_response TEXT NOT NULL DEFAULT '',
                item_results JSONB NOT NULL DEFAULT '[]'::jsonb,
                log_tail TEXT NOT NULL DEFAULT '',
                has_screenshot BOOLEAN NOT NULL DEFAULT FALSE,
                started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                finished_at TIMESTAMP WITH TIME ZONE
            );
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS runs_user_started_idx"
            " ON runs (user_id, started_at DESC);"
        )


"""
Run store
"""

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
RUN_ARTIFACTS_DIR = os.path.join(_BACKEND_DIR, "run_artifacts")
RUN_LOG_TAIL_LINES = 250


def insert_run(run_id: str, user_id: int, prompt: str) -> None:
    with get_cursor() as cursor:
        cursor.execute(
            "INSERT INTO runs (run_id, user_id, prompt) VALUES (%s, %s, %s);",
            (run_id, user_id, prompt),
        )


def finish_run(
    run_id: str,
    status_value: str,
    exit_reason: str,
    final_response: str,
    item_results: list,
    log_tail: str,
    has_screenshot: bool,
) -> None:
    with get_cursor() as cursor:
        cursor.execute(
            """
            UPDATE runs
            SET status = %s, exit_reason = %s, final_response = %s,
                item_results = %s::jsonb, log_tail = %s, has_screenshot = %s,
                finished_at = NOW()
            WHERE run_id = %s;
            """,
            (
                status_value,
                exit_reason[:500],
                final_response,
                json.dumps(item_results or []),
                log_tail,
                has_screenshot,
                run_id,
            ),
        )


def _run_row_to_dict(row) -> dict:
    return {
        "run_id": str(row[0]),
        "prompt": row[1],
        "status": row[2],
        "exit_reason": row[3],
        "final_response": row[4],
        "item_results": row[5] or [],
        "has_screenshot": bool(row[6]),
        "started_at": row[7].isoformat() if row[7] else None,
        "finished_at": row[8].isoformat() if row[8] else None,
    }


_RUN_COLUMNS = (
    "run_id, prompt, status, exit_reason, final_response,"
    " item_results, has_screenshot, started_at, finished_at"
)


"""
Document store

Files the agent can attach to web forms: resume, cover letter, transcript,
portfolio, anything the user labels. They live on disk per user, outside the
web root, one directory per document slug holding the file under its sanitized
original filename, so an employer receives "Edwin_Villanueva_Resume.pdf" rather
than "resume.pdf". Labels live in a per-user manifest.json; the listing itself
is derived from the directories, so a file removed by hand cannot leave a ghost
entry. Label, filename and path ride the credential blob into the agent
subprocess as `userDocuments` (see src/documents.py for the agents' side).

Files from the earlier two-slot store (`<slug>.<ext>` at the top of the user
directory) are still listed and are replaced cleanly.
"""

import re
import shutil

USER_DOCUMENTS_DIR = os.path.join(_BACKEND_DIR, "user_documents")
# Offered by the UI as suggestions; any label that slugifies to something
# non-empty is accepted.
DOCUMENT_SUGGESTED_LABELS = ("Resume", "Cover letter", "Transcript", "Portfolio", "Certification", "Photo")
DOCUMENT_EXTENSIONS = (".pdf", ".docx", ".doc", ".txt", ".rtf", ".odt", ".png", ".jpg", ".jpeg")
DOCUMENT_MAX_BYTES = 10 * 1024 * 1024
_DOCUMENT_MANIFEST = "manifest.json"
_DOCUMENT_SLUG = re.compile(r"^[a-z0-9_]{1,40}$")
_LEGACY_DOCUMENT_LABELS = {"resume": "Resume", "cover_letter": "Cover letter"}


def document_slug(label: str) -> str:
    """`Cover letter` -> `cover_letter`; empty when nothing usable remains."""
    slug = re.sub(r"[^a-z0-9]+", "_", (label or "").strip().lower()).strip("_")
    return slug[:40].rstrip("_")


def _document_label(slug: str, manifest: dict) -> str:
    label = manifest.get(slug)
    if isinstance(label, str) and label.strip():
        return label.strip()
    return _LEGACY_DOCUMENT_LABELS.get(slug) or slug.replace("_", " ").capitalize()


def _safe_document_filename(original: str, slug: str, extension: str) -> str:
    """The original filename with anything path-like or unprintable removed.

    The stem is sanitized on its own and the validated extension re-appended,
    so a name that is nothing but bad characters falls back to the slug
    instead of degenerating into `pdf.pdf`.
    """
    base = (original or "").replace("\\", "/").rsplit("/", 1)[-1]
    if extension and base.lower().endswith(extension):
        stem = base[: -len(extension)]
    else:
        stem = os.path.splitext(base)[0]
    stem = re.sub(r"[^A-Za-z0-9._ -]+", "", stem).strip(" .")
    stem = re.sub(r"\s+", " ", stem)[: 100 - len(extension)].strip(" .")
    return f"{stem or slug}{extension}"


def _document_dir(user_id: int) -> str:
    return os.path.join(USER_DOCUMENTS_DIR, str(int(user_id)))


def _read_document_manifest(user_id: int) -> dict:
    path = os.path.join(_document_dir(user_id), _DOCUMENT_MANIFEST)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            loaded = json.load(handle)
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _write_document_manifest(user_id: int, manifest: dict) -> None:
    directory = _document_dir(user_id)
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, _DOCUMENT_MANIFEST), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)


def _find_document(user_id: int, slug: str) -> str | None:
    """Absolute path of the stored document, or None."""
    directory = _document_dir(user_id)
    slug_dir = os.path.join(directory, slug)
    if os.path.isdir(slug_dir):
        for entry in sorted(os.listdir(slug_dir)):
            candidate = os.path.join(slug_dir, entry)
            if os.path.isfile(candidate) and os.path.splitext(entry)[1].lower() in DOCUMENT_EXTENSIONS:
                return candidate
    for ext in DOCUMENT_EXTENSIONS:
        legacy = os.path.join(directory, f"{slug}{ext}")
        if os.path.isfile(legacy):
            return legacy
    return None


def _document_slugs(user_id: int) -> list[str]:
    directory = _document_dir(user_id)
    if not os.path.isdir(directory):
        return []
    slugs: set[str] = set()
    for entry in os.listdir(directory):
        full = os.path.join(directory, entry)
        if os.path.isdir(full) and _DOCUMENT_SLUG.match(entry):
            slugs.add(entry)
        elif os.path.isfile(full):
            stem, ext = os.path.splitext(entry)
            if ext.lower() in DOCUMENT_EXTENSIONS and _DOCUMENT_SLUG.match(stem):
                slugs.add(stem)
    return sorted(slug for slug in slugs if _find_document(user_id, slug))


def list_user_documents(user_id: int) -> dict:
    """{slug: {label, filename, size, updated_at}} for the UI."""
    manifest = _read_document_manifest(user_id)
    out = {}
    for slug in _document_slugs(user_id):
        path = _find_document(user_id, slug)
        stat = os.stat(path)
        out[slug] = {
            "label": _document_label(slug, manifest),
            "filename": os.path.basename(path),
            "size": stat.st_size,
            "updated_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        }
    return out


def documents_for_agent(user_id: int) -> dict:
    """{slug: {label, filename, path}}: the `userDocuments` credential-blob entry."""
    manifest = _read_document_manifest(user_id)
    out = {}
    for slug in _document_slugs(user_id):
        path = _find_document(user_id, slug)
        out[slug] = {
            "label": _document_label(slug, manifest),
            "filename": os.path.basename(path),
            "path": path,
        }
    return out


def _remove_document_files(user_id: int, slug: str) -> None:
    directory = _document_dir(user_id)
    shutil.rmtree(os.path.join(directory, slug), ignore_errors=True)
    for ext in DOCUMENT_EXTENSIONS:
        legacy = os.path.join(directory, f"{slug}{ext}")
        if os.path.isfile(legacy):
            os.remove(legacy)


def store_document(user_id: int, label: str, original_filename: str, content: bytes) -> str:
    """Persist one document under its label and return the slug.

    Replaces any previous file stored under the same label, whichever layout
    it used.
    """
    slug = document_slug(label)
    extension = os.path.splitext(original_filename or "")[1].lower()
    filename = _safe_document_filename(original_filename, slug, extension)
    _remove_document_files(user_id, slug)
    slug_dir = os.path.join(_document_dir(user_id), slug)
    os.makedirs(slug_dir, exist_ok=True)
    with open(os.path.join(slug_dir, filename), "wb") as handle:
        handle.write(content)
    manifest = _read_document_manifest(user_id)
    manifest[slug] = label.strip()
    _write_document_manifest(user_id, manifest)
    return slug


def delete_document_files(user_id: int, slug: str) -> None:
    _remove_document_files(user_id, slug)
    manifest = _read_document_manifest(user_id)
    if slug in manifest:
        manifest.pop(slug, None)
        _write_document_manifest(user_id, manifest)


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


"""
Runs API
"""


@app.get('/api/runs')
async def list_runs(user_id: int = Depends(require_user)):
    """The caller's run history, newest first."""
    def query():
        with get_cursor(commit=False) as cursor:
            cursor.execute(
                f"SELECT {_RUN_COLUMNS} FROM runs"
                " WHERE user_id = %s ORDER BY started_at DESC LIMIT 50;",
                (user_id,),
            )
            return cursor.fetchall()
    rows = await asyncio.to_thread(query)
    return {"runs": [_run_row_to_dict(r) for r in rows], "error": ""}


def _load_owned_run(run_id: str, user_id: int):
    try:
        uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")
    with get_cursor(commit=False) as cursor:
        cursor.execute(
            f"SELECT {_RUN_COLUMNS}, log_tail FROM runs"
            " WHERE run_id = %s AND user_id = %s;",
            (run_id, user_id),
        )
        row = cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")
    return row


@app.get('/api/runs/{run_id}')
async def get_run(run_id: str, user_id: int = Depends(require_user)):
    row = await asyncio.to_thread(_load_owned_run, run_id, user_id)
    payload = _run_row_to_dict(row)
    payload["log_tail"] = row[9]
    return {"run": payload, "error": ""}


@app.get('/api/runs/{run_id}/screenshot')
async def get_run_screenshot(run_id: str, user_id: int = Depends(require_user)):
    """The run's final frame, captured from the live stream at run end."""
    await asyncio.to_thread(_load_owned_run, run_id, user_id)
    path = os.path.join(RUN_ARTIFACTS_DIR, f"{run_id}.jpg")
    if not os.path.isfile(path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No screenshot for this run.")
    return FileResponse(path, media_type="image/jpeg")


"""
Documents API
"""


def _documents_response(user_id: int) -> dict:
    return {
        "documents": list_user_documents(user_id),
        "suggested_labels": list(DOCUMENT_SUGGESTED_LABELS),
        "error": "",
    }


@app.get('/api/documents')
async def get_documents(user_id: int = Depends(require_user)):
    return await asyncio.to_thread(_documents_response, user_id)


@app.post('/api/documents')
async def upload_document(
    label: str = Form(...),
    file: UploadFile = File(...),
    user_id: int = Depends(require_user),
):
    if not document_slug(label):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Give the document a label with at least one letter or digit, e.g. Resume.",
        )
    extension = os.path.splitext(file.filename or "")[1].lower()
    if extension not in DOCUMENT_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type. Use one of: {', '.join(DOCUMENT_EXTENSIONS)}",
        )
    content = await file.read()
    if len(content) > DOCUMENT_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"File is larger than {DOCUMENT_MAX_BYTES // (1024 * 1024)} MB.",
        )
    await asyncio.to_thread(store_document, user_id, label, file.filename or "", content)
    return await asyncio.to_thread(_documents_response, user_id)


@app.delete('/api/documents/{slug}')
async def delete_document(slug: str, user_id: int = Depends(require_user)):
    # The slug comes from the client here, so it is validated before it is
    # used as a path component.
    if not _DOCUMENT_SLUG.match(slug):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid document id.")
    await asyncio.to_thread(delete_document_files, user_id, slug)
    return await asyncio.to_thread(_documents_response, user_id)


HITL_PREFIX = "@@HITL@@"

import json as _json

# Shared maps: (authenticated user_id, run_id) → asyncio.Queue / accepting flag.
# Keyed per RUN, not just per user: with one key per user, a second concurrent
# run overwrote the first run's queue and either run could eat the other's
# replies. The user id still comes from the token subject, never from a
# client-supplied parameter.
HITL_REPLY_QUEUES: dict[tuple[int, str], asyncio.Queue] = {}
# True only while we have sent CLARIFICATION and are waiting for stdin reply (user only).
HITL_ACCEPTING: dict[tuple[int, str], bool] = {}


def _accepting_run_ids(user_id: int) -> list[str]:
    """Run ids of this user's runs that are currently waiting for a reply."""
    return [
        rid for (uid, rid), accepting in HITL_ACCEPTING.items()
        if uid == user_id and accepting
    ]


def _queue_for_reply(user_id: int, run_id: str | None) -> tuple[asyncio.Queue | None, str]:
    """Resolve which run's queue a reply belongs to.

    Out-of-band channels (the REST endpoint, the chat fallback socket) do not
    carry a run id historically, so: an explicit run_id wins; otherwise the
    reply goes to the single accepting run, and with several accepting runs it
    is rejected rather than guessed.
    """
    if run_id:
        queue = HITL_REPLY_QUEUES.get((user_id, run_id))
        return queue, run_id if queue is not None else ""
    accepting = _accepting_run_ids(user_id)
    if len(accepting) == 1:
        return HITL_REPLY_QUEUES.get((user_id, accepting[0])), accepting[0]
    return None, ""

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
    body = await request.json()
    user_input = body.get("content", body.get("user_input", ""))
    requested_run = str(body.get("run_id") or "") or None
    queue, resolved_run = _queue_for_reply(user_id, requested_run)
    if queue is None or not HITL_ACCEPTING.get((user_id, resolved_run)):
        if len(_accepting_run_ids(user_id)) > 1:
            return {"status": "error", "message": "Several runs are waiting; include run_id."}
        return {"status": "error", "message": "No active clarification for this user."}
    await queue.put({"content": user_input})
    return {"status": "ok"}

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

    # Stored documents ride the credential blob (label, filename and path per
    # slug) so the agent's upload_file can attach them; src/documents.py is the
    # agents' side of this contract.
    documents = await asyncio.to_thread(documents_for_agent, user_id)
    if documents:
        credentials = {**credentials, "userDocuments": documents}

    # The run is a first-class record from the moment it starts: a refresh
    # must not erase what was asked or how it ended.
    try:
        await asyncio.to_thread(insert_run, run_id, user_id, prompt)
    except Exception as exc:
        print(f"[STREAM] Could not persist run row: {type(exc).__name__}")

    # Outcome tracking for the run record and the run_finished message.
    run_outcome = {"aborted": False, "final_response": "", "item_results": []}
    log_ring: deque[str] = deque(maxlen=RUN_LOG_TAIL_LINES)

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

    # Register a shared reply queue so any endpoint can push replies.
    # Keyed per (user, run): two concurrent runs must not eat each other's
    # replies.
    reply_queue = asyncio.Queue()
    hitl_key = (user_id, run_id)
    HITL_REPLY_QUEUES[hitl_key] = reply_queue
    HITL_ACCEPTING[hitl_key] = False

    # Mutable ref so the listener can dispatch input events once the relay is
    # attached (set after the browser comes up). Input handling itself lives in
    # cdp_stream.ScreencastRelay.
    relay_ref = {"relay": None}

    async def _dispatch_cdp_input(msg: dict):
        """Forward a browser input event from the frontend to the live view."""
        relay = relay_ref.get("relay")
        if relay is not None:
            await relay.dispatch_input(msg)

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
                        run_outcome["aborted"] = True
                        HITL_ACCEPTING[hitl_key] = False
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
                    and HITL_ACCEPTING.get(hitl_key)
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
                        run_outcome["final_response"] = hitl_message
                        raw_items = hitl_payload.get("item_results")
                        if isinstance(raw_items, list):
                            run_outcome["item_results"] = [
                                r for r in raw_items if isinstance(r, dict)
                            ]
                        await websocket.send_json({
                            "type": "RESPONSE",
                            "content": hitl_message,
                            "item_results": run_outcome["item_results"],
                        })
                        await websocket.send_json({
                            "type": "LOG",
                            "source": "AGENT",
                            "content": hitl_message,
                        })
                    else:
                        print(f"[HITL] Sending clarification request to frontend")
                        _drain_async_queue(reply_queue)
                        HITL_ACCEPTING[hitl_key] = True
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
                            # Structured close: the frontend keys its HITL
                            # state off this, not off log-substring matching.
                            try:
                                await websocket.send_json({"type": "HITL_CLOSED"})
                            except Exception:
                                pass
                        finally:
                            HITL_ACCEPTING[hitl_key] = False
                except Exception:
                    break
                continue

            # Regular log line
            print(f"[{log_type}] {content}")
            log_ring.append(f"[{log_type}] {content}")
            try:
                await websocket.send_json({"type": "LOG", "source": log_type, "content": content})
            except Exception:
                stream_disconnect_event.set()
                break

    log_task = asyncio.create_task(log_consumer())

    final_frame = None
    try:
        # 3. Attach to the agent's browser over raw CDP and stream it.
        # No Playwright here: the driver subprocess it spawns cannot start
        # under the SelectorEventLoop uvicorn uses on Windows with --reload,
        # which is how the live view silently died on Windows while the agent
        # kept running (docs/issues/phase-6-streaming.md).
        await websocket.send_json({"type": "STATUS", "content": "Warming up browser..."})
        relay = ScreencastRelay(
            port=port,
            send_bytes=websocket.send_bytes,
            send_json=websocket.send_json,
        )
        relay_ref["relay"] = relay

        async def _drop_stream_on_send_failure():
            await relay.send_failed.wait()
            stream_disconnect_event.set()

        send_failure_task = asyncio.create_task(_drop_stream_on_send_failure())
        try:
            started = False
            try:
                started = await relay.start()
            except Exception as exc:
                print(f"[STREAM] Live view attach failed: {type(exc).__name__}: {exc}")
            if not started:
                # The agent is fine; only the live view failed. Keep the socket
                # open so logs and HITL prompts still reach the user.
                print(f"[STREAM] No page target appeared on port {port}; continuing without the live view.")
                try:
                    await websocket.send_json({
                        "type": "STATUS",
                        "content": "Live browser view unavailable; the agent is still running.",
                    })
                except Exception:
                    pass
            await _wait_for_process_or_disconnect(process, stream_disconnect_event)
        finally:
            send_failure_task.cancel()
            relay_ref["relay"] = None
            # The newest frame is the run's visual evidence; keep it before
            # the connection goes away.
            final_frame = relay.latest_frame
            await relay.close()

    finally:
        # 5. Cleanup
        exit_code = process.poll()
        exit_reason = (
            "agent process exited" if exit_code is not None
            else "client disconnected" if stream_disconnect_event.is_set()
            else "handler returned"
        )
        print(f"[STREAM] Run finished for user_id={user_id}: {exit_reason} (exit code {exit_code}).")

        stream_disconnect_event.set()
        HITL_REPLY_QUEUES.pop(hitl_key, None)
        HITL_ACCEPTING.pop(hitl_key, None)

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

        # ── Run outcome: status, artifact, persistence, structured message ──
        if run_outcome["aborted"]:
            run_status, run_exit_reason = "aborted", "stopped by user"
        elif run_outcome["final_response"] and (exit_code in (None, 0)):
            run_status, run_exit_reason = "succeeded", "completed with a final response"
        elif exit_code not in (None, 0):
            run_status, run_exit_reason = "failed", f"agent process exited with code {exit_code}"
        elif stream_disconnect_event.is_set() and not run_outcome["final_response"]:
            run_status, run_exit_reason = "failed", "client disconnected before the run finished"
        else:
            run_status, run_exit_reason = "failed", "ended without a final response"

        has_screenshot = False
        if final_frame:
            try:
                os.makedirs(RUN_ARTIFACTS_DIR, exist_ok=True)
                with open(os.path.join(RUN_ARTIFACTS_DIR, f"{run_id}.jpg"), "wb") as handle:
                    handle.write(final_frame)
                has_screenshot = True
            except Exception as exc:
                print(f"[STREAM] Could not save run screenshot: {type(exc).__name__}")

        try:
            await asyncio.to_thread(
                finish_run,
                run_id,
                run_status,
                run_exit_reason,
                run_outcome["final_response"],
                run_outcome["item_results"],
                "\n".join(log_ring),
                has_screenshot,
            )
        except Exception as exc:
            print(f"[STREAM] Could not persist run outcome: {type(exc).__name__}")

        try:
            await websocket.send_json({
                "type": "run_finished",
                "run_id": run_id,
                "status": run_status,
                "exit_reason": run_exit_reason,
                "has_screenshot": has_screenshot,
            })
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

            try:
                payload = _json.loads(data)
            except (ValueError, TypeError):
                payload = {"content": data}
            if not isinstance(payload, dict):
                payload = {"content": str(payload)}

            requested_run = str(payload.get("run_id") or "") or None
            queue, _resolved = _queue_for_reply(user_id, requested_run)
            if queue is None:
                waiting = len(_accepting_run_ids(user_id))
                message = (
                    "Several runs are waiting; include run_id."
                    if waiting > 1
                    else "No agent is currently waiting for input."
                )
                try:
                    await websocket.send_json({"type": "STATUS", "content": message})
                except Exception:
                    break
                continue

            await queue.put(payload)
            print(f"[HITL] Forwarded chat message to agent for user {user_id}")
    except WebSocketDisconnect:
        pass
    finally:
        await _close_websocket(websocket, code=1000, reason="closed")

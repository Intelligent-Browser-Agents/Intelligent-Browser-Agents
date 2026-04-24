# FastAPI framework, Requests for anything but GET
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from playwright.async_api import async_playwright
import socket

# ForJWT Gen
import jwt
from datetime import datetime, timezone, timedelta

# Used for Ensuring Startup and Shutdown Events
from contextlib import asynccontextmanager

# Database Config and Connection
import yaml
import psycopg2

# For loading .env variables
import os
from dotenv import load_dotenv

# Password hashing (import once at load time; native bcrypt + reload/re-import can misbehave)
import bcrypt

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

import asyncio
import json
import time
import tempfile

# credential storage 
CREDENTIALS_BY_SESSION = {}
SESSION_CREDENTIAL_CREATED_AT = {}
SESSION_CREDENTIAL_TTL_SECONDS = 60 * 30

# Windows requires ProactorEventLoop for asyncio subprocess support.
if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception as e:
        print(f"Warning: could not set Windows Proactor event loop policy: {e}")

"""
To-DO List:
-Create Verify Email endpoint, using app.get and token sent as query param
"""


# Global Variables
conn = None #postgres connection
cur = None #postgres terminal cursor
userdb_config_path = 'configs/user_db_config.yaml'
userdb_config = None
PORT_POOL = asyncio.Queue()
SINGLE_WORKER_LOCK_FD = None
SINGLE_WORKER_LOCK_PATH = os.path.join(tempfile.gettempdir(), "iba_backend_single_worker.lock")


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _acquire_single_worker_lock() -> None:
    """Ensure only one backend worker process runs at a time.

    This server keeps HITL/session routing in process-local memory. Running multiple
    workers can route related requests to different processes and break interaction
    handoffs. Set ALLOW_UNSAFE_MULTIWORKER=1 to bypass this guard intentionally.
    """
    global SINGLE_WORKER_LOCK_FD

    if os.getenv("ALLOW_UNSAFE_MULTIWORKER", "").lower() in {"1", "true", "yes"}:
        print("[startup] ALLOW_UNSAFE_MULTIWORKER is enabled; skipping single-worker guard.")
        return

    lock_message = (
        "Detected multiple backend worker processes. This backend uses in-memory "
        "HITL/session state and must run with a single worker for reliable "
        "interaction handoff. Use '--workers 1' and avoid request-based worker "
        "recycling for long-lived WebSocket sessions. Set ALLOW_UNSAFE_MULTIWORKER=1 "
        "only if you fully externalize shared state (e.g., Redis)."
    )

    for _ in range(2):
        try:
            fd = os.open(SINGLE_WORKER_LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("ascii", errors="ignore"))
            SINGLE_WORKER_LOCK_FD = fd
            return
        except FileExistsError:
            existing_pid = -1
            try:
                with open(SINGLE_WORKER_LOCK_PATH, "r", encoding="ascii", errors="ignore") as handle:
                    existing_pid = int((handle.read() or "-1").strip())
            except Exception:
                existing_pid = -1

            if not _pid_is_running(existing_pid):
                try:
                    os.remove(SINGLE_WORKER_LOCK_PATH)
                    continue
                except OSError:
                    pass
            raise RuntimeError(lock_message)

    raise RuntimeError(lock_message)


def _release_single_worker_lock() -> None:
    global SINGLE_WORKER_LOCK_FD

    fd = SINGLE_WORKER_LOCK_FD
    if fd is None:
        return

    SINGLE_WORKER_LOCK_FD = None
    try:
        os.close(fd)
    except OSError:
        pass

    try:
        with open(SINGLE_WORKER_LOCK_PATH, "r", encoding="ascii", errors="ignore") as handle:
            holder_pid = int((handle.read() or "-1").strip())
    except Exception:
        holder_pid = -1

    if holder_pid == os.getpid():
        try:
            os.remove(SINGLE_WORKER_LOCK_PATH)
        except OSError:
            pass

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic: initialize the database connection
    global conn
    global cur
    global userdb_config
    # read connection parameters, for security setup a config file for db params
    #params = config()
    print('Loading environment variables...')
    # Do not expand $... inside values (default dotenv treats $ as variable refs).
    load_dotenv(interpolate=False)
    _acquire_single_worker_lock()
    
    print("Getting Database Config File")
    try:
        with open(userdb_config_path, 'r') as file:
            userdb_config = yaml.safe_load(file)
    except FileNotFoundError:
        print(f"Error: The file '{userdb_config_path}' was not found.")
    except yaml.YAMLError as e:
        print(f"Error parsing YAML file: {e}")

    # connect to the PostgreSQL server
    print('Connecting to the PostgreSQL database...')
    conn = psycopg2.connect(
        dbname = userdb_config['dbname'],
        user = userdb_config['user'],
        password = userdb_config['password'],
        port = userdb_config['port'],
        host = userdb_config['host']
    )
    conn.autocommit = True
    # create a cursor
    cur = conn.cursor()
    print("Database connected!")

    while not PORT_POOL.empty():
        await PORT_POOL.get()
            
    for p in range(9000,9010): # Using 9000+ 
        await PORT_POOL.put(p)
    print(f"✅ POOL READY: {PORT_POOL.qsize()} ports available.")
    
    yield
    # Shutdown logic: close the database connection
    print("Closing database connection...")
    if cur is not None:
        cur.close()
        print('Cursor closed')
    if conn is not None:
        conn.close()
        print('Database connection closed.')
    _release_single_worker_lock()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Your React URL
    allow_credentials=True,
    allow_methods=["*"], # This allows POST, OPTIONS, etc.
    allow_headers=["*"],
)

"""
Helper Functions
"""
def user_exists(username: str, email: str) -> bool:
    query = 'SELECT * FROM users WHERE username = %s OR email = %s;'
    cur.execute(query, (username, email))
    results = cur.fetchone()
    return results is not None

def user_exists_id(userId: int) -> bool:
    query = 'SELECT * FROM users WHERE user_id = %s;'
    cur.execute(query, (str(userId),))
    results = cur.fetchone()
    return results is not None


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
@app.get('/api/users/') # Get User by Id
async def get_user(request: Request):
    #incoming: userId or JWT
    #outgoing: username, firstname, lastname, email
    error  = ''

    token = request.headers['authorization'].split(' ')[1] if 'authorization' in request.headers else ''
    userId = -1

    # Checking values in query exists 
    if request.query_params.get('userId') == ''  and (token == '' or token == 'undefined'):
        error = 'No UserId or Token Specified'
        return {'error' : error}
    
    if request.query_params.get('userId') is not None:
        userId = int(request.query_params.get('userId', 0))
    else:
        try:
            secret_key = os.getenv('TOKEN_SECRET')
            decoded = jwt.decode(token, secret_key, algorithms='HS256')
            userId = decoded['user_id']
        except jwt.InvalidTokenError as e:
            error = str(e)
            return {'error': error}

    if userId <= 0: #Validate User
        error = 'UserId is Invalid'
        return {'error' : error}
    
    query = 'SELECT * FROM users WHERE user_id = %s;'
    cur.execute(query, (str(userId),))
    results = cur.fetchone()
    
    if results is not None:
        user_id, username, firstname, lastname, email, _, _, _, _ = results
        return {'user_id': user_id, 'username': username, 'firstname': firstname, 'lastname':lastname, 'email':email,'error': error}
    else:
        error = f'No Users Found in Database'
        return {'error': error}
    
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
    cur.execute(query, (username, firstname, lastname, email, False, False, hashed_password))
    newUserId = cur.fetchone()[0]
    return {'userId': newUserId, 'error': error}

@app.delete('/api/users/delete/') # Delete User
async def delete_user(request: Request):
    #incoming: token
    #outgoing: success/failure
    error  = ''
    token = request.headers['authorization'].split(' ')[1] if 'authorization' in request.headers else ''

    userId = 0

    if token != '':
        try:
            secret_key = os.getenv('TOKEN_SECRET')
            decoded = jwt.decode(token, secret_key, algorithms='HS256')
            userId = decoded['user_id']
        except jwt.InvalidTokenError as e:
            return {'error': e}
    else:
        error = 'No Token Provided'
        return {'error' : error}

    if userId <= 0: #Validate User
        error = 'UserId is Not Specified or Invalid'
        return {'error' : error}
    
    check = user_exists_id(userId)
    if check is False:
        error = 'No User Found with the Given UserId'
        return {'error' : error}
    
    # Deleting the user
    query = 'DELETE FROM users WHERE user_id = %s;'
    cur.execute(query, (str(userId),))
    
    return {'error': error}

@app.post('/api/users/update/') # Update User Info
async def update_user(request: Request):
    #incoming: token, username, firstname, lastname, email, password
    #outgoing: new user info
    error  = ''
    pass_updated = False

    token = request.headers['authorization'].split(' ')[1] if 'authorization' in request.headers else ''
    body = await request.json()

    userId = 0

    if token != '':
        try:
            secret_key = os.getenv('TOKEN_SECRET')
            decoded = jwt.decode(token, secret_key, algorithms='HS256')
            userId = decoded['user_id']
        except jwt.InvalidTokenError as e:
            error = str(e)
            return {'error': error}
    else:
        error = 'No Token Provided'
        return {'error' : error}

    
    username = body['username'] if 'username' in body else None
    firstname = body['firstname'] if 'firstname' in body else None
    lastname = body['lastname'] if 'lastname' in body else None
    email = body['email'] if 'email' in body else None
    password = body['password'] if 'password' in body else None

    if userId <= 0: #Validate User
        error = 'UserId is Not Specified or Invalid'
        return {'error' : error}
    
    check = user_exists_id(userId)
    if check is False:
        error = 'No User Found with the Given UserId'
        return {'error' : error}
    
    if username is not None:
        query = 'UPDATE users SET username = %s WHERE user_id = %s;'
        cur.execute(query, (username, str(userId)))
    if firstname is not None:
        query = 'UPDATE users SET firstname = %s WHERE user_id = %s;'
        cur.execute(query, (firstname, str(userId)))
    if lastname is not None:
        query = 'UPDATE users SET lastname = %s WHERE user_id = %s;'
        cur.execute(query, (lastname, str(userId)))
    if email is not None:
        query = 'UPDATE users SET email = %s WHERE user_id = %s;'
        cur.execute(query, (email, str(userId)))
    if password is not None:
        query = 'UPDATE users SET password = %s, chng_pass = false WHERE user_id = %s;'
        hashed_password = hash_password_bcrypt(password)
        cur.execute(query, (hashed_password, str(userId)))
        pass_updated = True
    
    query = 'SELECT * FROM users WHERE user_id = %s;'
    cur.execute(query, (str(userId),))
    results = cur.fetchone()
    if results is not None:
        user_id, username, firstname, lastname, email, _, _, _, _ = results
        return {'user_id': user_id, 'username': username, 'firstname': firstname, 'lastname':lastname, 'email':email,'passUpdated': pass_updated,'error': error}
    else:
        error = f'No Users Found in Database'
        return {'error': error}
    
@app.post('/api/users/login/') # User Login
async def login_user(request: Request):
    #incoming: username, password, token(Optional)
    #outgoing: token
    error  = ''
    token = request.headers['authorization'].split(' ')[1] if 'authorization' in request.headers else ''
    body = await request.json()

    if token != '' and token != 'undefined':
        try:
            secret_key = os.getenv('TOKEN_SECRET')
            decoded = jwt.decode(token, secret_key, algorithms='HS256')
            return {'token': token, 'error': error}
        except jwt.InvalidTokenError as e:
            error = str(e)

    username = body['username']
    password = body['password']

    #print(password)

    if username == '' or password == '':
        error = 'Username or Password is Missing'
        return {'error' : error}

    query = (
        "SELECT user_id, username, firstname, lastname, password, chng_pass "
        "FROM users WHERE username = %s;"
    )
    cur.execute(query, (username,))
    results = cur.fetchone()

    if results is not None:
        user_id, username, firstname, lastname, stored_hash, chng_pass = results
        if not verify_password(password, stored_hash):
            results = None

    if results is not None:
        if chng_pass == True:
            error = 'Password Change Required'
        secret_key = os.getenv('TOKEN_SECRET')
        # Generate JWT Token
        payload = {
            'user_id': user_id,
            'username': username,
            'firstname': firstname,
            'lastname': lastname,
            'exp': datetime.now(timezone.utc) + timedelta(hours=1)  # Token expires in 1 hour
        }
        token = jwt.encode(payload, secret_key, algorithm='HS256')
        error = ''
        return {'token': token, 'error': error}
    else:
        error = 'Invalid Username or Password'
        return {'error': error}

@app.post('/api/users/verify/') # Verify logged-in user by token + password
async def verify_user(request: Request):
    token = request.headers['authorization'].split(' ')[1] if 'authorization' in request.headers else ''
    body = await request.json()
    password = body['password'] if 'password' in body else ''

    if token in ('', 'undefined', 'null', 'None'):
        return {'verified': False, 'error': 'No Token Provided'}
    if password == '':
        return {'verified': False, 'error': 'Password is Missing'}

    try:
        secret_key = os.getenv('TOKEN_SECRET')
        decoded = jwt.decode(token, secret_key, algorithms='HS256')
        user_id = decoded.get('user_id')
    except jwt.InvalidTokenError as e:
        return {'verified': False, 'error': str(e)}

    if user_id is None:
        return {'verified': False, 'error': 'Invalid token payload'}

    query = "SELECT password FROM users WHERE user_id = %s;"
    cur.execute(query, (str(user_id),))
    result = cur.fetchone()

    if result is None or not verify_password(password, result[0]):
        return {'verified': False, 'error': 'Invalid password'}

    return {'verified': True, 'error': ''}
    
@app.get('/api/users/forgot-password/') # User Forgot Password
async def forgot_password(request: Request):
    #incoming: username or email
    #outgoing: success/failure
    error  = ''

    # Checking values in query exists 
    if len(request.query_params) == 0 or (request.query_params.get('username') == None and request.query_params.get('email') == None):
        error = 'No username or email Specified'
        return {'error' : error}
    
    username = request.query_params.get('username') if 'username' in request.query_params else None
    email = request.query_params.get('email') if 'email' in request.query_params else None
    print(email)
    
    if username != None:
        query = 'SELECT email, user_id FROM users WHERE username = %s;'
        cur.execute(query, (username,))
        results = cur.fetchone()
    else: 
        query = 'SELECT email, user_id FROM users WHERE email = %s;'
        cur.execute(query, (email,))
        results = cur.fetchone()

    if results is not None:
        email = results[0]
        userId = results[1]
        new_password = secrets.token_hex(6) # Generate a secure random password
        hashed_password = hash_password_bcrypt(new_password)
        query = 'UPDATE users SET password = %s, chng_pass = true WHERE user_id = %s;'
        cur.execute(query, (hashed_password, str(userId)))
        send_forgot_password(email, new_password)
        return {'error': error}
    else:
        error = f'No Users Found in Database'
        return {'error': error} 


"""
Placeholder for Agent API Endpoints
"""


""" ===== EDWIN TEST ENDPOINTS ===== """
# # todo: handle user input and start app.py on the user's hardware
@app.post('/api/start_agent')
async def start_agent(requests: Request): 

    # get user's input from frontend
    body = await requests.json()
    user_input = body.get("user_input")
    print("TEST: ", user_input) 


    # send user input to app.py
    #! start the agent on the SERVER
    # start main with subprocess
    current_env = os.environ.copy()
    current_env["PYTHONIOENCODING"] = "utf-8"
    python_path = sys.executable

    result = subprocess.run(
        [python_path, f'src/app.py', '--prompt', user_input, '--video_port', '10000'],
        env=current_env,
        capture_output=True,
        text=True
    )

    return {"STDOUT": result.stdout, "STDERR": result.stderr}

# store credetials from this session
@app.post('/api/users/store-credentials')
async def store_credentials(request: Request): 
    body = await request.json()
    session_id = body.get("session_id")
    credentials = body.get("credentials", {})

    if not session_id: 
        return {"ok": False, "error": "session_id is required."}

    _prune_stale_session_credentials()
    CREDENTIALS_BY_SESSION[session_id] = credentials
    SESSION_CREDENTIAL_CREATED_AT[session_id] = time.monotonic()
    return {"ok": True, "error": ""}


async def wait_for_port(port: int, timeout: float = 10.0):
    start_time = asyncio.get_event_loop().time()
    while asyncio.get_event_loop().time() - start_time < timeout:
        try:
            conn = await asyncio.get_event_loop().run_in_executor(
                None, lambda: socket.create_connection(("127.0.0.1", port), timeout=0.5)
            )
            conn.close()
            return True
        except:
            await asyncio.sleep(0.5)
    return False

HITL_PREFIX = "@@HITL@@"

import json as _json

# Shared map: user_id → asyncio.Queue  for HITL replies.
# Any endpoint (REST, /ws/chat, or /ws/stream) can push a reply here.
HITL_REPLY_QUEUES: dict[str, asyncio.Queue] = {}
# True only while we have sent CLARIFICATION and are waiting for stdin reply (user only).
HITL_ACCEPTING: dict[str, bool] = {}

USER_HITL_REPLY_TYPE = "user_hitl_reply"
ABORT_RUN_TYPE = "abort_run"


def _is_stop_command(text: str) -> bool:
    value = (text or "").strip().lower()
    return value in {"stop", "cancel", "quit", "exit", "abort"}


def _drain_async_queue(q: asyncio.Queue) -> None:
    while True:
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            break


def _prune_stale_session_credentials() -> None:
    """Drop expired session credential blobs to keep memory bounded."""
    now = time.monotonic()
    stale_ids = [
        session_id
        for session_id, created_at in SESSION_CREDENTIAL_CREATED_AT.items()
        if now - created_at > SESSION_CREDENTIAL_TTL_SECONDS
    ]
    for session_id in stale_ids:
        CREDENTIALS_BY_SESSION.pop(session_id, None)
        SESSION_CREDENTIAL_CREATED_AT.pop(session_id, None)


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


@app.post("/api/hitl_reply/{user_id}")
async def hitl_reply(user_id: str, request: Request):
    """REST endpoint the frontend can call to answer a clarification request."""
    if not HITL_ACCEPTING.get(user_id):
        return {"status": "error", "message": "No active clarification for this user_id."}
    body = await request.json()
    user_input = body.get("content", body.get("user_input", ""))
    queue = HITL_REPLY_QUEUES.get(user_id)
    if queue is None:
        return {"status": "error", "message": "No agent is waiting for input with that user_id."}
    await queue.put({"content": user_input})
    return {"status": "ok"}

async def _switch_to_new_page(new_page, start_screencast_fn):
    """Wait for a popup/new-tab page to load, then switch screencast to it."""
    try:
        await new_page.wait_for_load_state("domcontentloaded", timeout=10000)
        await start_screencast_fn(new_page)
    except Exception as exc:
        print(f"[screencast] Failed to switch to new tab: {exc}")


@app.websocket("/ws/stream/{user_id}")
async def stream_endpoint(websocket: WebSocket, user_id: str):
    await websocket.accept()
    print("DEBUG 1: Socket Accepted")

    stream_disconnect_event = asyncio.Event()

    query_params = websocket.query_params
    prompt = query_params.get("prompt", "Default Prompt")
    session_id = query_params.get("session_id")

    _prune_stale_session_credentials()
    credentials = CREDENTIALS_BY_SESSION.pop(session_id, {}) if session_id else {}
    if session_id:
        SESSION_CREDENTIAL_CREATED_AT.pop(session_id, None)
    credentials_json = json.dumps(credentials)
    print(f"[STREAM] session_id={session_id} credentials={credentials}")

    print("Prompt Received in WebSocket Endpoint: ")

    port = await PORT_POOL.get()
    print(f"DEBUG 2: Got Port {port}")

    current_env = os.environ.copy()
    current_env["PYTHONUNBUFFERED"] = "1"
    current_env["PYTHONIOENCODING"] = "utf-8"
    python_path = sys.executable
    loop = asyncio.get_running_loop()

    # 1. Launch Agent with stdin pipe for HITL replies
    def start_process():
        return subprocess.Popen(
            [python_path, "src/app.py", "--port", str(port), "--prompt", prompt, "--credentials_json", credentials_json],
            env=current_env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
    process = await loop.run_in_executor(None, start_process)
    print("DEBUG 3: Agent Subprocess Started")

    # 2. Feed stdout/stderr into asyncio queue via threads
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
                        print(f"[HITL] Stop requested via WebSocket: {content[:200]!r}")
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
                        print(f"[HITL] Received user_hitl_reply via WebSocket: {content[:200]!r}")
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
                                print(f"[HITL] Got reply: {str(user_input)[:200]}")
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
                    browser = await p.chromium.connect_over_cdp(f"http://localhost:{port}")
                    context = browser.contexts[0]
                    page = context.pages[0]
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
            await websocket.send_json({"type": "STATUS", "content": "Browser failed to open."})

    finally:
        # 5. Cleanup
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

from typing import List
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        stale_connections: List[WebSocket] = []
        for connection in list(self.active_connections):
            try:
                await connection.send_text(message)
            except Exception:
                stale_connections.append(connection)

        for stale in stale_connections:
            self.disconnect(stale)

manager = ConnectionManager()

@app.websocket("/ws/chat/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: int):
    await manager.connect(websocket)

    query_params = websocket.query_params
    token = query_params.get("token", "Default Prompt")
    try:
        while True:
            data = await websocket.receive_text()
            print(f"Received message from client #{client_id}: {data}")

            # Forward to any waiting HITL agent for this user
            queue = HITL_REPLY_QUEUES.get(str(client_id))
            if queue is not None:
                try:
                    payload = _json.loads(data)
                except (ValueError, TypeError):
                    payload = {"content": data}
                await queue.put(payload)
                print(f"[HITL] Forwarded chat message to agent for client {client_id}")

            await manager.broadcast(f"Client #{client_id} says: {data}")
    except WebSocketDisconnect:
        await manager.broadcast(f"Client #{client_id} left the chat")
    finally:
        manager.disconnect(websocket)

# todo: generate response for user to see the progress of the main script as it runs (as chat bubbles)
@app.get('/send_logs')
async def send_logs(requests: Request): 
    
    # get output from app.py
    # send app.py output to the frontend
    pass 

# Testing memory fix
import gc

@app.get("/api/nuke")
async def manual_cleanup():
    # 1. Clear any global result lists/dicts here (e.g. results.clear())
    # 2. Force garbage collection
    gc.collect()
    return {"message": "GC triggered"}

# # test endpoint
# @app.get('/')
# def test():
#     return {"message": "This works!"}

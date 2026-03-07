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

# For password hashing
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


import asyncio
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

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic: initialize the database connection
    global conn
    global cur
    global userdb_config
    # read connection parameters, for security setup a config file for db params
    #params = config()
    print('Loading environment variables...')
    load_dotenv()
    
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
    """conn = psycopg2.connect(
        dbname = userdb_config['dbname'],
        user = userdb_config['user'],
        password = userdb_config['password'],
        port = userdb_config['port'],
        host = userdb_config['host']
    )
    conn.autocommit = True
    # create a cursor
    cur = conn.cursor()
    """
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

    

app = FastAPI(lifespan=lifespan)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*", "https://100.49.61.97"], # Your React URL
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
    hashed_password = bcrypt.hashpw(password.encode('utf-8'), os.getenv('BCRYPT_SALT').encode('utf-8'))
    hashed_password = hashed_password.decode('utf-8')
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
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), os.getenv('BCRYPT_SALT').encode('utf-8'))
        hashed_password = hashed_password.decode('utf-8')
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
            return {'error': str(e)}
        
    username = body['username']
    password = body['password']

    #print(password)

    if username == '' or password == '':
        error = 'Username or Password is Missing'
        return {'error' : error}
    
    hashed_password = bcrypt.hashpw(password.encode('utf-8'), os.getenv('BCRYPT_SALT').encode('utf-8'))
    hashed_password = hashed_password.decode('utf-8')
    
    #print(hashed_password)

    query = 'SELECT * FROM users WHERE username = %s AND password = %s;'
    cur.execute(query, (username, hashed_password))
    results = cur.fetchone()
    
    if results is not None:
        user_id, username, firstname, lastname, _, _, _, _, chng_pass = results
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

    hashed_password = bcrypt.hashpw(password.encode('utf-8'), os.getenv('BCRYPT_SALT').encode('utf-8'))
    hashed_password = hashed_password.decode('utf-8')

    query = 'SELECT user_id FROM users WHERE user_id = %s AND password = %s;'
    cur.execute(query, (str(user_id), hashed_password))
    result = cur.fetchone()

    if result is None:
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
        hashed_password = bcrypt.hashpw(new_password.encode('utf-8'), os.getenv('BCRYPT_SALT').encode('utf-8'))
        hashed_password = hashed_password.decode('utf-8')
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
    python_path = sys.executable

    result = subprocess.run(
        [python_path, f'src/app.py', '--prompt', user_input, '--video_port', '10000'],
        env=current_env,
        capture_output=True,
        text=True
    )

    return {"STDOUT": result.stdout, "STDERR": result.stderr}

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

@app.websocket("/ws/stream/{user_id}")
async def stream_endpoint(websocket: WebSocket, user_id: str):
    await websocket.accept()
    print("DEBUG 1: Socket Accepted")

    query_params = websocket.query_params
    prompt = query_params.get("prompt", "Default Prompt")
    print("Prompt Received in WebSocket Endpoint: ")

    port = await PORT_POOL.get()
    print(f"DEBUG 2: Got Port {port}")

    current_env = os.environ.copy()
    python_path = sys.executable
    
    # 1. Launch Agent with full pipe access
    process = await asyncio.create_subprocess_exec(
        python_path, "src/app.py", "--port", str(port), "--prompt", prompt,
        env=current_env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    print("DEBUG 3: Agent Subprocess Started")

    is_ready = await wait_for_port(port)
    print(f"DEBUG 4: Browser Ready: {is_ready}")

    # 2. Monitor Logs in the background
    async def log_reader(pipe, log_type):
        while True:
            line = await pipe.readline()
            if not line: break
            content = line.decode().strip()
            print(f"[{log_type}] {content}")
            await websocket.send_json({"type": "LOG", "source": log_type, "content": content})

    # Start log monitoring tasks
    stdout_task = asyncio.create_task(log_reader(process.stdout, "STDOUT"))
    stderr_task = asyncio.create_task(log_reader(process.stderr, "STDERR"))

    try:
        # 3. Wait for Browser
        await websocket.send_json({"type": "STATUS", "content": "Warming up browser..."})
        if await wait_for_port(port):
            async with async_playwright() as p:
                browser = await p.chromium.connect_over_cdp(f"http://localhost:{port}")
                page = browser.contexts[0].pages[0]
                client = await page.context.new_cdp_session(page)

                # 4. Stream Setup
                async def on_frame(payload):
                    try:
                        await websocket.send_json({"type": "FRAME", "data": payload['data']})
                        await client.send("Page.screencastFrameAck", {"sessionId": payload['sessionId']})
                    except: pass

                client.on("Page.screencastFrame", on_frame)
                await client.send("Page.startScreencast", {"format": "jpeg", "quality": 40})
                
                # Keep alive until process ends
                await process.wait()
        else:
            await websocket.send_json({"type": "STATUS", "content": "Browser failed to open."})

    finally:
        # 5. Cleanup
        stdout_task.cancel()
        stderr_task.cancel()
        if process.returncode is None:
            process.terminate()
        await PORT_POOL.put(port)

from typing import List
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)

manager = ConnectionManager()

@app.websocket("/ws/stream/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: int):
    await manager.connect(websocket)
    try:
        while True:
            # Wait for message from a client
            data = await websocket.receive_text()
            print(f"Received message from client #{client_id}: {data}")
            # Broadcast it to everyone else
            await manager.broadcast(f"Client #{client_id} says: {data}")
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        await manager.broadcast(f"Client #{client_id} left the chat")


# todo: generate response for user to see the progress of the main script as it runs (as chat bubbles)
@app.get('/send_logs')
async def send_logs(requests: Request): 
    
    # get output from app.py
    # send app.py output to the frontend
    pass 

# # test endpoint
# @app.get('/')
# def test():
#     return {"message": "This works!"}

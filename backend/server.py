# FastAPI framework, Requests for anything but GET
from fastapi import FastAPI, Request 
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

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


"""
To-DO List:
-Create Verify Email endpoint, using app.get and token sent as query param
"""

# # Global Variables
# conn = None #postgres connection
# cur = None #postgres terminal cursor
# userdb_config_path = 'configs/user_db_config.yaml'
# userdb_config = None

# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     # Startup logic: initialize the database connection
#     global conn
#     global cur
#     global userdb_config
#     # read connection parameters, for security setup a config file for db params
#     #params = config()
#     print('Loading environment variables...')
#     load_dotenv()
    
#     print("Getting Database Config File")
#     try:
#         with open(userdb_config_path, 'r') as file:
#             userdb_config = yaml.safe_load(file)
#     except FileNotFoundError:
#         print(f"Error: The file '{userdb_config_path}' was not found.")
#     except yaml.YAMLError as e:
#         print(f"Error parsing YAML file: {e}")

#     # connect to the PostgreSQL server
#     print('Connecting to the PostgreSQL database...')
#     conn = psycopg2.connect(dbname = userdb_config['dbname'],
#                             user = userdb_config['user'],
#                             password = userdb_config['password'],
#                             port = userdb_config['port'],
#                             host = userdb_config['host'])
#     conn.autocommit = True
#     # create a cursor
#     cur = conn.cursor()
#     print("Database connected!")
#     yield
#     # Shutdown logic: close the database connection
#     print("Closing database connection...")
#     if cur is not None:
#         cur.close()
#         print('Cursor closed')
#     if conn is not None:
#         conn.close()
#         print('Database connection closed.')
    

# app = FastAPI(lifespan=lifespan)
app = FastAPI()     # for testing frontend/backend endpoints (EDWIN)

# add CORS so that the UI can access the server from localhost.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# """
# Helper Functions
# """
# def user_exists(username: str, email: str) -> bool:
#     query = 'SELECT * FROM users WHERE username = %s OR email = %s;'
#     cur.execute(query, (username, email))
#     results = cur.fetchone()
#     return results is not None

# def user_exists_id(userId: int) -> bool:
#     query = 'SELECT * FROM users WHERE user_id = %s;'
#     cur.execute(query, (str(userId),))
#     results = cur.fetchone()
#     return results is not None

# def send_forgot_password(to_email: str, new_password: str) -> None:
#     from_email = os.getenv('EMAIL_ACCOUNT')
#     from_password = os.getenv('EMAIL_PASSWORD')

#     subject = "Password Reset - Intelligent Browser Agents"
#     body = f"Your new password is: {new_password}\nPlease change it after logging in."

#     msg = MIMEMultipart()
#     msg['From'] = from_email
#     msg['To'] = to_email
#     msg['Subject'] = subject

#     msg.attach(MIMEText(body, 'plain'))

#     try:
#         server = smtplib.SMTP('smtp.gmail.com', 587)
#         server.starttls()
#         server.login(from_email, from_password)
#         text = msg.as_string()
#         server.sendmail(from_email, to_email, text)
#         server.quit()
#         print(f"Password reset email sent to {to_email}")
#     except Exception as e:
#         print(f"Failed to send email: {e}")


# """
# User CRUD Endpoints
# """
# @app.get('/api/users/') # Get User by Id
# async def get_user(request: Request):
#     #incoming: userId
#     #outgoing: username, firstname, lastname, email
#     error  = ''

#     # Checking values in query exists 
#     if len(request.query_params) == 0 or request.query_params.get('userId') == '':
#         error = 'No UserId Specified'
#         return {'error' : error}

#     userId = int(request.query_params.get('userId', 0))

#     if userId <= 0: #Validate User
#         error = 'UserId is Invalid'
#         return {'error' : error}
    
#     query = 'SELECT * FROM users WHERE user_id = %s;'
#     cur.execute(query, (str(userId),))
#     results = cur.fetchone()
    
#     if results is not None:
#         user_id, username, firstname, lastname, email, _, _, _, _ = results
#         return {'user_id': user_id, 'username': username, 'firstname': firstname, 'lastname':lastname, 'email':email,'error': error}
#     else:
#         error = f'No Users Found in Database'
#         return {'error': error}
    

# @app.post('/api/users/insert/') # Insert New User 
# async def insert_user(request: Request):
#     #incoming: username, firstname, lastname, email, password
#     #outgoing: UserId
#     error  = ''
#     body = await request.json()

#     username = body['username'] if 'username' in body else ''
#     firstname = body['firstname'] if 'firstname' in body else ''
#     lastname = body['lastname'] if 'lastname' in body else ''
#     email = body['email'] if 'email' in body else ''
#     password = body['password'] if 'password' in body else ''

#     # Checking values in query
#     if username == '' or firstname == '' or lastname == '' or email == '' or password == '':
#         error = 'One or More Required Fields are Missing'
#         return {'error' : error}
    
#     # Check if the user already exists
#     check = user_exists(username, email)
#     if check is True:
#         error = 'Username or Email Already Exists'
#         return {'error' : error}
    
#     # Inserting the new user
#     query = 'INSERT INTO users (username, firstname, lastname, email, password, isverified) VALUES (%s, %s, %s, %s, %s, %s) RETURNING user_id;'
#     hashed_password = bcrypt.hashpw(password.encode('utf-8'), os.getenv('BCRYPT_SALT').encode('utf-8'))
#     hashed_password = hashed_password.decode('utf-8')
#     cur.execute(query, (username, firstname, lastname, email, hashed_password, False))
#     newUserId = cur.fetchone()[0]
#     return {'userId': newUserId, 'error': error}

# @app.delete('/api/users/delete/') # Delete User
# async def delete_user(request: Request):
#     #incoming: token
#     #outgoing: success/failure
#     error  = ''
#     token = request.headers['authorization'].split(' ')[1] if 'authorization' in request.headers else ''

#     userId = 0

#     if token != '':
#         try:
#             secret_key = os.getenv('TOKEN_SECRET')
#             decoded = jwt.decode(token, secret_key, algorithms='HS256')
#             userId = decoded['user_id']
#         except jwt.InvalidTokenError as e:
#             return {'error': e}
#     else:
#         error = 'No Token Provided'
#         return {'error' : error}

#     if userId <= 0: #Validate User
#         error = 'UserId is Not Specified or Invalid'
#         return {'error' : error}
    
#     check = user_exists_id(userId)
#     if check is False:
#         error = 'No User Found with the Given UserId'
#         return {'error' : error}
    
#     # Deleting the user
#     query = 'DELETE FROM users WHERE user_id = %s;'
#     cur.execute(query, (str(userId),))
    
#     return {'error': error}

# @app.post('/api/users/update/') # Update User Info
# async def update_user(request: Request):
#     #incoming: token, username, firstname, lastname, email, password
#     #outgoing: new user info
#     error  = ''
#     pass_updated = False

#     token = request.headers['authorization'].split(' ')[1] if 'authorization' in request.headers else ''
#     body = await request.json()

#     userId = 0

#     if token != '':
#         try:
#             secret_key = os.getenv('TOKEN_SECRET')
#             decoded = jwt.decode(token, secret_key, algorithms='HS256')
#             userId = decoded['user_id']
#         except jwt.InvalidTokenError as e:
#             error = str(e)
#             return {'error': error}
#     else:
#         error = 'No Token Provided'
#         return {'error' : error}

    
#     username = body['username'] if 'username' in body else None
#     firstname = body['firstname'] if 'firstname' in body else None
#     lastname = body['lastname'] if 'lastname' in body else None
#     email = body['email'] if 'email' in body else None
#     password = body['password'] if 'password' in body else None

#     if userId <= 0: #Validate User
#         error = 'UserId is Not Specified or Invalid'
#         return {'error' : error}
    
#     check = user_exists_id(userId)
#     if check is False:
#         error = 'No User Found with the Given UserId'
#         return {'error' : error}
    
#     if username is not None:
#         query = 'UPDATE users SET username = %s WHERE user_id = %s;'
#         cur.execute(query, (username, str(userId)))
#     if firstname is not None:
#         query = 'UPDATE users SET firstname = %s WHERE user_id = %s;'
#         cur.execute(query, (firstname, str(userId)))
#     if lastname is not None:
#         query = 'UPDATE users SET lastname = %s WHERE user_id = %s;'
#         cur.execute(query, (lastname, str(userId)))
#     if email is not None:
#         query = 'UPDATE users SET email = %s WHERE user_id = %s;'
#         cur.execute(query, (email, str(userId)))
#     if password is not None:
#         query = 'UPDATE users SET password = %s, chng_pass = false WHERE user_id = %s;'
#         hashed_password = bcrypt.hashpw(password.encode('utf-8'), os.getenv('BCRYPT_SALT').encode('utf-8'))
#         hashed_password = hashed_password.decode('utf-8')
#         cur.execute(query, (hashed_password, str(userId)))
#         pass_updated = True
    
#     query = 'SELECT * FROM users WHERE user_id = %s;'
#     cur.execute(query, (str(userId),))
#     results = cur.fetchone()
#     if results is not None:
#         user_id, username, firstname, lastname, email, _, _, _, _ = results
#         return {'user_id': user_id, 'username': username, 'firstname': firstname, 'lastname':lastname, 'email':email,'passUpdated': pass_updated,'error': error}
#     else:
#         error = f'No Users Found in Database'
#         return {'error': error}
    
# @app.post('/api/users/login/') # User Login
# async def login_user(request: Request):
#     #incoming: username, password, token(Optional)
#     #outgoing: token
#     error  = ''
#     token = request.headers['authorization'].split(' ')[1] if 'authorization' in request.headers else ''
#     body = await request.json()

#     if token != '':
#         try:
#             secret_key = os.getenv('TOKEN_SECRET')
#             decoded = jwt.decode(token, secret_key, algorithms='HS256')
#             return {'token': token, 'error': error}
#         except jwt.InvalidTokenError as e:
#             return {'error': e}
        
#     username = body['username']
#     password = body['password']

#     print(password)

#     if username == '' or password == '':
#         error = 'Username or Password is Missing'
#         return {'error' : error}
    
#     hashed_password = bcrypt.hashpw(password.encode('utf-8'), os.getenv('BCRYPT_SALT').encode('utf-8'))
#     hashed_password = hashed_password.decode('utf-8')
    
#     print(hashed_password)

#     query = 'SELECT * FROM users WHERE username = %s AND password = %s;'
#     cur.execute(query, (username, hashed_password))
#     results = cur.fetchone()
    
#     if results is not None:
#         user_id, username, firstname, lastname, _, _, _, _, chng_pass = results
#         if chng_pass == True:
#             error = 'Password Change Required'
#         secret_key = os.getenv('TOKEN_SECRET')
#         # Generate JWT Token
#         payload = {
#             'user_id': user_id,
#             'username': username,
#             'firstname': firstname,
#             'lastname': lastname,
#             'exp': datetime.now(timezone.utc) + timedelta(hours=1)  # Token expires in 1 hour
#         }
#         token = jwt.encode(payload, secret_key, algorithm='HS256')
#         return {'token': token, 'error': error}
#     else:
#         error = 'Invalid Username or Password'
#         return {'error': error}
    
# @app.get('/api/users/forgot-password/') # User Forgot Password
# async def forgot_password(request: Request):
#     #incoming: username or email
#     #outgoing: success/failure
#     error  = ''

#     # Checking values in query exists 
#     if len(request.query_params) == 0 or (request.query_params.get('username') == None and request.query_params.get('email') == None):
#         error = 'No username or email Specified'
#         return {'error' : error}
    
#     username = request.query_params.get('username') if 'username' in request.query_params else None
#     email = request.query_params.get('email') if 'email' in request.query_params else None
    
#     if username != None:
#         query = 'SELECT email, user_id FROM users WHERE username = %s;'
#         cur.execute(query, (username,))
#         results = cur.fetchone()
#     else: 
#         query = 'SELECT email, user_id FROM users WHERE email = %s;'
#         cur.execute(query, (email,))
#         results = cur.fetchone()

#     if results is not None:
#         email = results[0]
#         userId = results[1]
#         new_password = secrets.token_hex(6) # Generate a secure random password
#         hashed_password = bcrypt.hashpw(new_password.encode('utf-8'), os.getenv('BCRYPT_SALT').encode('utf-8'))
#         hashed_password = hashed_password.decode('utf-8')
#         query = 'UPDATE users SET password = %s, chng_pass = true WHERE user_id = %s;'
#         cur.execute(query, (hashed_password, str(userId)))
#         send_forgot_password(email, new_password)
#         return {'error': error}
#     else:
#         error = f'No Users Found in Database'
#         return {'error': error} 


# """
# Placeholder for Agent API Endpoints
# """


"""
Endpoints for frontend/backend interaction
"""

# # todo: handle user input and start app.py on the user's hardware
@app.post('/start_agent')
async def start_agent(requests: Request): 



    # get user's input from frontend
    body = await requests.json()
    user_input = body.get("user_input")
    print("TEST: ", user_input) 

    # send user input to app.py
    #? Do we start the agent on the SERVER or on the USER'S COMPUTER?


@app.get('/')
def test():
    return {"message": "This works!"}
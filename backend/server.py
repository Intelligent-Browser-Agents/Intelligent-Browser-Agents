from fastapi import FastAPI, Request # FastAPI framework, Requests for anything but GET

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
from dotenv import load_dotenv, set_key

# For password hashing
import bcrypt

"""
To-DO List:
"""


# Global Variables
conn = None #postgres connection
cur = None #postgres terminal cursor
userdb_config_path = 'configs/user_db_config.yaml'
userdb_config = None

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
    conn = psycopg2.connect(dbname = userdb_config['dbname'],
                            user = userdb_config['user'],
                            password = userdb_config['password'],
                            port = userdb_config['port'],
                            host = userdb_config['host'])
    conn.autocommit = True
    # create a cursor
    cur = conn.cursor()
    print("Database connected!")
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
    cur.execute(query, (str(userId)))
    results = cur.fetchone()
    return results is not None


"""
User CRUD Endpoints
"""
@app.get('/api/users/') # Get User by Id
async def get_user(request: Request):
    #incoming: userId
    #outgoing: username, firstname, lastname, email
    error  = ''

    # Checking values in query exists 
    if len(request.query_params) == 0 or request.query_params.get('userId') == '':
        error = 'No UserId Specified'
        return {'error' : error}

    userId = int(request.query_params.get('userId', 0))

    if userId <= 0: #Validate User
        error = 'UserId is Invalid'
        return {'error' : error}
    
    query = 'SELECT * FROM users WHERE user_id = %s;'
    cur.execute(query, (str(userId)))
    results = cur.fetchone()
    
    if results is not None:
        user_id, username, firstname, lastname, email, _, _, _ = results
        return {'user_id': user_id, 'username': username, 'firstname': firstname, 'lastname':lastname, 'email':email,'error': error}
    else:
        error = f'No Users Found in Database'
        return {'error': error}
    

@app.post('/api/users/insert/') # Insert New User 
async def insert_user(request: Request):
    #incoming: username, firstname, lastname, email, password
    #outgoing: UserId->Now, JWT->later
    error  = ''
    body = await request.json()

    username = body['username']
    firstname = body['firstname']
    lastname = body['lastname']
    email = body['email']
    password = body['password']

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
    query = 'INSERT INTO users (username, firstname, lastname, email, password, isverified) VALUES (%s, %s, %s, %s, %s, %s) RETURNING user_id;'
    hashed_password = bcrypt.hashpw(password.encode('utf-8'), os.getenv('BCRYPT_SALT').encode('utf-8'))
    hashed_password = hashed_password.decode('utf-8')
    cur.execute(query, (username, firstname, lastname, email, hashed_password, False))
    newUserId = cur.fetchone()[0]
    return {'userId': newUserId, 'error': error}

@app.delete('/api/users/delete/')
async def delete_user(request: Request):
    #incoming: token
    #outgoing: success/failure
    error  = ''
    token = request.headers['authorization'].split(' ')[1] if 'authorization' in request.headers else ''
    
    body = await request.json()

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
    cur.execute(query, (str(userId)))
    
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
            return {'error': e}
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
        query = 'UPDATE users SET password = %s WHERE user_id = %s;'
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), os.getenv('BCRYPT_SALT').encode('utf-8'))
        hashed_password = hashed_password.decode('utf-8')
        cur.execute(query, (hashed_password, str(userId)))
        pass_updated = True
    
    query = 'SELECT * FROM users WHERE user_id = %s;'
    cur.execute(query, (str(userId)))
    results = cur.fetchone()
    if results is not None:
        user_id, username, firstname, lastname, email, _, _, _ = results
        return {'user_id': user_id, 'username': username, 'firstname': firstname, 'lastname':lastname, 'email':email,'passUpdated': pass_updated,'error': error}
    else:
        error = f'No Users Found in Database'
        return {'error': error}
    
@app.post('/api/users/login/')
async def login_user(request: Request):
    #incoming: username, password, token(Optional)
    #outgoing: JWT token
    error  = ''
    token = request.headers['authorization'].split(' ')[1] if 'authorization' in request.headers else ''
    body = await request.json()

    if token != '':
        try:
            secret_key = os.getenv('TOKEN_SECRET')
            decoded = jwt.decode(token, secret_key, algorithms='HS256')
            return {'token': token, 'error': error}
        except jwt.InvalidTokenError as e:
            return {'error': e}
        
    username = body['username']
    password = body['password']

    if username == '' or password == '':
        error = 'Username or Password is Missing'
        return {'error' : error}
    
    hashed_password = bcrypt.hashpw(password.encode('utf-8'), os.getenv('BCRYPT_SALT').encode('utf-8'))
    hashed_password = hashed_password.decode('utf-8')
    
    query = 'SELECT * FROM users WHERE username = %s AND password = %s;'
    cur.execute(query, (username, hashed_password))
    results = cur.fetchone()
    
    if results is not None:
        user_id, username, firstname, lastname, _, _, _, _ = results
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



"""
Placeholder for Agent API Endpoints
"""


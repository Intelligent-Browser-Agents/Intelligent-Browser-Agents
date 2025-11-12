from fastapi import FastAPI
import json
from contextlib import asynccontextmanager
import psycopg2




conn = None #postgres connection
cur = None #postgres terminal cursor

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic: initialize the database connection
    global conn
    global cur
    # read connection parameters, for security setup a config file for db params
    #params = config()

    # connect to the PostgreSQL server
    print('Connecting to the PostgreSQL database...')
    conn = psycopg2.connect(dbname="user_database",
                            user="postgres",
                            password="password",
                            host="localhost")
    
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



#User CRUD OPs
@app.get('/api/users/') # Get User by Id
async def get_user(userId: int = 0):
    #incoming: userId
    #outgoing: username, firstname, lastname, email
    error  = ''

    if userId <= 0: #Validate User
        error = 'UserId is Not Specified or Invalid'
        return {'error' : error}
    
    query = 'SELECT * FROM users WHERE user_id = %s;'
    cur.execute(query, (str(userId)))
    results = cur.fetchone()
    
    if results is not None:
        user_id, username, firstname, lastname, email, _, _ = results
        return {'user_id': user_id, 'username': username, 'firstname': firstname, 'lastname':lastname, 'email':email,'error': error}
    else:
        error = f'No Users Found in Database'
        return {'error': error}
    

@app.post('/api/users/insert/')
async def insert_user():
    #incoming: username, firstname, lastname, email, password
    #outgoing: UserId->Now, JWT->later
    error  = ''
    return {'error': error}


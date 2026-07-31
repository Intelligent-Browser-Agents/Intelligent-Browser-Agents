# Database Readme

To get and run a chromadb instance use
```bash
docker pull chromadb/chroma
docker run -d -p 8001:8000 chromadb/chroma
```

Host port 8001 is deliberate: the API server below binds 8000, so mapping Chroma
to 8000 as well would collide. Chroma is optional and nothing in the agent
pipeline currently imports it.

To get and run a postgress docker
```bash
docker pull postgres
docker run --name some-postgres -e POSTGRES_PASSWORD=mysecretpassword -p 5432:5432 -d postgres
```
--name some-postgres: Assigns a name to your container for easier identification.\
-e POSTGRES_PASSWORD=mysecretpassword: Sets the password for the default postgres superuser. This is mandatory.\
-p 5432:5432: Maps port 5432 on your local machine to port 5432 inside the container, allowing external connections.\
-d: Runs the container in detached mode, meaning it runs in the background.\
postgres: Specifies the Docker image to use.

You will need to modify `backend/configs/user_db_config.yaml` to account for the username and password you have selected, as well as the host port you are running this database on. The following example works for the example commands displayed above:
```
dbname : "postgres"
user : "postgres"
password : "mysecretpassword"
port : "5432"
host : "127.0.0.1"
```

Before we can run the uvicorn server, we must create the Users table. This must be done through docker's command line. 

Connect in terminal to postgres
```bash
    psql -h localhost -U postgres -p 5432 -d postgres
```

- (Note: if you'd like to use postgres from your command line instead of Docker's, run this command:
  `docker exec -it some-postgres psql -U postgres -d postgres`, `\dt` to view tables, and `\q` to quit.

-(if that doesn't work, try running `docker ps` to list the docker instances running and use the name you see there instead)

Check for tables using the following command: `\l`


Used to create the table
```SQL

CREATE TABLE Users (
    user_id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    firstname VARCHAR(50) NOT NULL,
    lastname VARCHAR(50) NOT NULL,
    email VARCHAR(50) UNIQUE NOT NULL,
    isverified BOOLEAN NOT NULL,
    createdat TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    chng_pass BOOLEAN NOT NULL,
    password VARCHAR(255) NOT NULL
);

```
- user_database is the database
- users is the table

To add a new user: 
```SQL
INSERT INTO users (username, firstname, lastname, email, isverified, chng_pass, password)
VALUES ('testuser', 'Caleb', 'Yaghoubi', 'test@email.com', true, false, example_password);
```

To run uvicorn
```bash
    uvicorn server:app --host 127.0.0.1 --port 8000 --reload 
```

You may get Bcrypt errors. If so, you do not have the right values in your `.env` file. Let one of us know to help you with this. 

Testing

Run from the repository root, where `pyproject.toml` holds the pytest config:
```bash
pytest -q
```

Server tests only:
```bash
pytest backend/tests/test_server.py -v
```

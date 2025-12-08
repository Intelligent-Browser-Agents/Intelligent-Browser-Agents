# Database Readme
To get and run a chromadb instance use 
```bash
docker pull chromadb/chroma
docker run -d -p 8000:8000 chromadb/chroma
```

To get and run a postgress docker
```bash
docker pull postgres
docker run --name some-postgres -e POSTRGRES_PASSWORD=mysecretpassword -p 5432:5432 -d postgres
```
--name some-postgres: Assigns a name to your container for easier identification.\
-e POSTGRES_PASSWORD=mysecretpassword: Sets the password for the default postgres superuser. This is mandatory.\
-p 5432:5432: Maps port 5432 on your local machine to port 5432 inside the container, allowing external connections.\
-d: Runs the container in detached mode, meaning it runs in the background.\
postgres: Specifies the Docker image to use.

To run uvicorn
```bash
    uvicorn server:app --host 127.0.0.1 --port 8000 --reload 
```

Connect in terminal to postgres
```bash
    psql -h localhost -U postgres -p 5432 -d user_database
```

- user_database is the database
- users is the table

Used to create the table
CREATE TABLE Users (
    user_id SERIAL PRIMARY KEY,
    username VarChar(50) UNIQUE NOT NULL,
    firstname VarChar(50) NOT NULL,
    lastname VarChar(50) NOT NULL,
    email VarChar(50) UNIQUE NOT NULL,
    isverified BOOLEAN NOT NULL,
    createdat TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

Adding a new user 
INSERT INTO users (username, firstname, lastname, email, isverified)
VALUES ('testuser', 'Caleb', 'Yaghoubi', 'test@email.com', true);

Testing 
pytest -q testing.py
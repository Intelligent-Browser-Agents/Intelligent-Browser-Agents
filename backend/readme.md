# Database Readme
To get and run a chromadb instance use 
```bash
docker pull chromadb/chroma
docker run -d -p 8000:8000 chromadb/chroma
```

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

Adding a new user 
```SQL
INSERT INTO users (username, firstname, lastname, email, isverified, chng_pass)
VALUES ('testuser', 'Caleb', 'Yaghoubi', 'test@email.com', true, false);
```
Testing 
```bash
pytest -q testing.py
```

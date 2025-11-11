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
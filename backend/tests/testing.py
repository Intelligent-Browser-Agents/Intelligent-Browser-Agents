from fastapi.testclient import TestClient
from ..server import app

client = TestClient(app)

print('hello, world')
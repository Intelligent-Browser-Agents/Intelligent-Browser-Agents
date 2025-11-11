from fastapi import FastAPI

app = FastAPI()


@app.get("/api")
async def read_root():
    return {"message": "Hello from FastAPI and Uvicorn!"}

@app.get("/api/items/{item_id}")
async def read_item(item_id: int):
    return {"item_id": item_id, "message": f"This is item {item_id}"}
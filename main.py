# main.py
from fastapi import FastAPI

app = FastAPI()

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/webhook")
async def webhook_stub():
    return {"status": "received"}
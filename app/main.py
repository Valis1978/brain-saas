from fastapi import FastAPI
from app.api.endpoints import telegram, intent

app = FastAPI(title="Brain SaaS API", version="0.1.0")

@app.get("/")
async def root():
    return {"message": "Brain SaaS API is online 🧬"}

@app.get("/health")
async def health():
    return {"status": "healthy"}

# Include routers
app.include_router(telegram.router, prefix="/api/v1/telegram", tags=["telegram"])

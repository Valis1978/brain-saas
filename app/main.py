from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.api.endpoints import telegram, google, cron
from app.services.scheduler_service import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle - start/stop scheduler."""
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="Brain SaaS API", version="0.2.0", lifespan=lifespan)

@app.get("/")
async def root():
    return {"message": "Brain SaaS API is online 🧬"}

@app.get("/health")
async def health():
    return {"status": "healthy"}

# Include routers
app.include_router(telegram.router, prefix="/api/v1/telegram", tags=["telegram"])
app.include_router(cron.router, prefix="/api/v1/cron", tags=["cron"])
app.include_router(google.router)


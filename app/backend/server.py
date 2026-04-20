from fastapi import FastAPI, APIRouter
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List
import uuid
from datetime import datetime, timezone
from routes import auth_routes, project_routes, upload_routes, takeoff_routes, blog_routes, stripe_routes, export_routes

# Import database and models
from database import engine, Base
import models

# ── NEW: Import AI engine ─────────────────────────────────────────
# Drop best.pt into backend/models/ after Colab training completes
try:
    from ai.inference_api import TakeoffAIInference
    AI_MODEL_PATH = os.environ.get("AI_MODEL_PATH", "models/best.pt")
    ai_engine = TakeoffAIInference.get_instance(AI_MODEL_PATH)
    print(f"[TakeOff.ai] AI engine loaded: {AI_MODEL_PATH}")
except Exception as e:
    ai_engine = None
    print(f"[TakeOff.ai] AI engine not loaded (mock mode): {e}")
# ──────────────────────────────────────────────────────────────────

# Load environment variables
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Create database tables
Base.metadata.create_all(bind=engine)

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Create FastAPI app
app = FastAPI(
    title="TakeOff.ai API",
    description="Backend API for TakeOff.ai SaaS platform",
    version="1.0.0",
    redirect_slashes=False
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

api_router = APIRouter(prefix="/api")

app.include_router(auth_routes.router,    prefix="/api")
app.include_router(project_routes.router, prefix="/api")
app.include_router(upload_routes.router,  prefix="/api")
app.include_router(takeoff_routes.router, prefix="/api")
app.include_router(blog_routes.router,    prefix="/api")
app.include_router(stripe_routes.router,  prefix="/api")
app.include_router(export_routes.router,  prefix="/api")

from routes.stripe_routes import stripe_webhook
app.post("/api/webhook/stripe")(stripe_webhook)

@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "TakeOff.ai API",
        "version": "1.0.0",
        "ai_engine": "loaded" if ai_engine and ai_engine.model else "mock_mode"
    }

@app.get("/api")
async def root():
    return {"message": "TakeOff.ai API v1.0", "docs": "/docs", "health": "/api/health"}

class StatusCheck(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class StatusCheckCreate(BaseModel):
    client_name: str

@api_router.get("/")
async def _root():
    return {"message": "Hello World"}

@api_router.post("/status", response_model=StatusCheck)
async def create_status_check(input: StatusCheckCreate):
    status_dict = input.model_dump()
    status_obj = StatusCheck(**status_dict)
    doc = status_obj.model_dump()
    doc['timestamp'] = doc['timestamp'].isoformat()
    _ = await db.status_checks.insert_one(doc)
    return status_obj

@api_router.get("/status", response_model=List[StatusCheck])
async def get_status_checks():
    status_checks = await db.status_checks.find({}, {"_id": 0}).to_list(1000)
    for check in status_checks:
        if isinstance(check['timestamp'], str):
            check['timestamp'] = datetime.fromisoformat(check['timestamp'])
    return status_checks

app.include_router(api_router)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
logger.info("TakeOff.ai API started successfully")

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()

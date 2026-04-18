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
    redirect_slashes=False  # Disable automatic trailing slash redirects
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Include routers with /api prefix
app.include_router(auth_routes.router, prefix="/api")
app.include_router(project_routes.router, prefix="/api")
app.include_router(upload_routes.router, prefix="/api")
app.include_router(takeoff_routes.router, prefix="/api")
app.include_router(blog_routes.router, prefix="/api")  # Public, no auth    
app.include_router(stripe_routes.router, prefix="/api")
app.include_router(export_routes.router, prefix="/api")                   

# Stripe webhook endpoint (must be at /api/webhook/stripe)
from routes.stripe_routes import stripe_webhook
app.post("/api/webhook/stripe")(stripe_webhook)                                  

# Health check endpoint
@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "TakeOff.ai API",
        "version": "1.0.0"
    }

@app.get("/api")
async def root():
    return {
        "message": "TakeOff.ai API v1.0",
        "docs": "/docs",
        "health": "/api/health"
    }

# Define Models
class StatusCheck(BaseModel):
    model_config = ConfigDict(extra="ignore")  # Ignore MongoDB's _id field
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class StatusCheckCreate(BaseModel):
    client_name: str

# Add your routes to the router instead of directly to app
@api_router.get("/")
async def root():
    return {"message": "Hello World"}

@api_router.post("/status", response_model=StatusCheck)
async def create_status_check(input: StatusCheckCreate):
    status_dict = input.model_dump()
    status_obj = StatusCheck(**status_dict)
    
    # Convert to dict and serialize datetime to ISO string for MongoDB
    doc = status_obj.model_dump()
    doc['timestamp'] = doc['timestamp'].isoformat()
    
    _ = await db.status_checks.insert_one(doc)
    return status_obj

@api_router.get("/status", response_model=List[StatusCheck])
async def get_status_checks():
    # Exclude MongoDB's _id field from the query results
    status_checks = await db.status_checks.find({}, {"_id": 0}).to_list(1000)
    
    # Convert ISO string timestamps back to datetime objects
    for check in status_checks:
        if isinstance(check['timestamp'], str):
            check['timestamp'] = datetime.fromisoformat(check['timestamp'])
    
    return status_checks

# Include the router in the main app
app.include_router(api_router)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


logger.info("TakeOff.ai API started successfully")

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
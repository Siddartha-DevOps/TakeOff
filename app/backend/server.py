from fastapi import FastAPI
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
import os
import logging
from pathlib import Path
from routes import auth_routes, project_routes, upload_routes, takeoff_routes, blog_routes, stripe_routes, export_routes, scale_routes, condition_routes, correction_routes, ai_routes, compare_routes, eval_routes, handoff_routes, realtime_routes, team_routes, repeating_routes, webhook_routes, folder_routes

# Import models so every relationship("ClassName") string reference across
# the ORM mapper registry resolves before the app starts handling requests.
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

# Schema is Alembic-owned now (run `alembic upgrade head` before starting
# the server — see backend/alembic/). Base.metadata.create_all() used to run
# here, which is exactly the "no migrations applied" gap this fixes: it
# silently diverges from what's actually tracked/versioned, and can't apply
# things a migration can (e.g. `CREATE EXTENSION postgis`, dropping enum
# types on rollback). Schema changes now only happen through `alembic upgrade`.

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

app.include_router(auth_routes.router,    prefix="/api")
app.include_router(project_routes.router, prefix="/api")
app.include_router(upload_routes.router,  prefix="/api")
app.include_router(takeoff_routes.router, prefix="/api")
app.include_router(blog_routes.router,    prefix="/api")
app.include_router(stripe_routes.router,  prefix="/api")
app.include_router(export_routes.router,  prefix="/api")
app.include_router(scale_routes.router,   prefix="/api")
app.include_router(condition_routes.router, prefix="/api")
app.include_router(correction_routes.router, prefix="/api")
app.include_router(ai_routes.router,      prefix="/api")
app.include_router(compare_routes.router, prefix="/api")
app.include_router(eval_routes.router,    prefix="/api")
app.include_router(handoff_routes.router, prefix="/api")
app.include_router(realtime_routes.router, prefix="/api")
app.include_router(realtime_routes.collab_router, prefix="/api")
app.include_router(team_routes.router, prefix="/api")
app.include_router(repeating_routes.router, prefix="/api")
app.include_router(webhook_routes.router, prefix="/api")
app.include_router(folder_routes.router, prefix="/api")

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

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
logger.info("TakeOff.ai API started successfully")

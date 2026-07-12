from fastapi import FastAPI
from routes import auth_routes
app = FastAPI(title="TakeOff auth (local demo)")
app.include_router(auth_routes.router, prefix="/api")
@app.get("/healthz")
def healthz(): return {"ok": True}

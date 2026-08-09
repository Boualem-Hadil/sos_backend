"""
SOS Algérie — FastAPI Backend
Entry point: uvicorn main:app --reload
"""
import json
import logging
import os
import time
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

load_dotenv()

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("sos_backend")

# ── Import routes (after env is loaded) ──────────────────────────────────────
from app.routes import auth, users, emergencies, companies, events, medical, admin
from app.database import engine
from app import models
from app.scheduler import create_scheduler


# ── App lifespan ──────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 SOS Algérie backend starting up …")
    # Create all tables if they don't exist (dev convenience — use Alembic in prod)
    models.Base.metadata.create_all(bind=engine)
    # Start license-expiry scheduler
    scheduler = create_scheduler()
    scheduler.start()
    logger.info("⏰ License expiry scheduler started (runs daily at 08:00)")
    yield
    scheduler.shutdown(wait=False)
    logger.info("🛑 SOS Algérie backend shutting down …")


# ── FastAPI instance ──────────────────────────────────────────────────────────
app = FastAPI(
    title       = "SOS Algérie API",
    description = "B2B emergency management platform for industrial companies in Algeria",
    version     = "1.0.0",
    docs_url    = "/docs",
    redoc_url   = "/redoc",
    lifespan    = lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
raw_origins = os.getenv("CORS_ORIGINS", '["*"]')
try:
    origins = json.loads(raw_origins)
except Exception:
    origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins     = origins if origins != ["*"] else ["*"],
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)

# ── Request logging middleware ─────────────────────────────────────────────────
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = (time.perf_counter() - start) * 1000
    logger.info(
        "%s %s → %d  (%.1f ms)",
        request.method,
        request.url.path,
        response.status_code,
        elapsed,
    )
    return response


# ── Global error handler — never expose raw Python tracebacks ─────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR,
        content     = {
            "success": False,
            "data":    None,
            "message": "An unexpected error occurred. Please try again later.",
        },
    )


# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(emergencies.router)
app.include_router(companies.router)
app.include_router(events.router)
app.include_router(medical.router)
app.include_router(admin.router)


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/", tags=["Health"])
def root():
    return {"success": True, "message": "SOS Algérie API is running", "version": "1.0.0"}


@app.get("/health", tags=["Health"])
def health():
    return {"status": "ok"}

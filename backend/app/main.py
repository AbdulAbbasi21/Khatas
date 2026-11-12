"""
Khataz API.

Run:  uvicorn app.main:app --reload        (from the backend folder)
Docs: http://localhost:8000/docs
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.routers import ai, auth, businesses, chats, home, ledger, paypal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

async def _paypal_loop():
    """Every few minutes, match pending payments against receivers' PayPal transactions."""
    from app.core.database import SessionLocal
    from app.services import autocheck

    from datetime import datetime, timedelta, timezone

    while True:
        autocheck.LIVE["loop_next"] = datetime.now(timezone.utc) + timedelta(seconds=settings.paypal_sync_seconds)
        await asyncio.sleep(settings.paypal_sync_seconds)
        try:
            await run_in_threadpool(autocheck.run_all, SessionLocal)
        except Exception:
            logging.getLogger("khataz.autocheck").exception("background PayPal check failed")
        finally:
            autocheck.LIVE["loop_last"] = datetime.now(timezone.utc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_paypal_loop()) if settings.paypal_sync_seconds > 0 else None
    yield
    if task:
        task.cancel()


app = FastAPI(
    lifespan=lifespan,
    title="Khataz API",
    version="0.1.0",
    description="Shared business credit ledger with PayPal payment verification.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(OperationalError)
async def database_down(request: Request, exc: OperationalError):
    logging.getLogger("khataz").error("Database error: %s", exc.orig)
    return JSONResponse(status_code=503, content={
        "detail": "Can't reach the database. Start Docker Desktop, then run "
                  "'docker compose up -d' in the project folder, and try again."})


@app.exception_handler(ValueError)
async def value_error(request: Request, exc: ValueError):
    # invalid money / currency values raised from services
    return JSONResponse(status_code=400, content={"detail": str(exc)})


for r in (auth.router, businesses.router, ledger.router, home.router, paypal.router, ai.router, chats.router):
    app.include_router(r)


@app.get("/api/health", tags=["health"])
def health():
    return {"status": "ok"}

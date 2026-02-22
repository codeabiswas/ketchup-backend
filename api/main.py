# api/main.py

"""FastAPI application entry point."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import (
    auth,
    availability,
    availability_group,
    feedback,
    groups,
    plans,
    users,
)
from config import get_settings
from database import db
from utils.invite_expiry import expire_stale_invites_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    await db.connect()

    # Start the invite expiry cron as a background task.
    # Runs every 5 minutes, expires pending invites older than 24 hours.
    expiry_task = asyncio.create_task(expire_stale_invites_loop())

    yield

    # Clean shutdown: cancel cron before disconnecting DB
    expiry_task.cancel()
    try:
        await expiry_task
    except asyncio.CancelledError:
        pass
    await db.disconnect()


app = FastAPI(
    title="Ketchup API",
    description="AI-powered social coordination platform",
    version="0.1.0",
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(groups.router)
app.include_router(plans.router)
app.include_router(availability.router)
app.include_router(availability_group.router)
app.include_router(feedback.router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def root():
    return {"message": "Ketchup API", "docs": "/docs"}

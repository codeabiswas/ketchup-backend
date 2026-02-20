"""FastAPI application entry point."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from database import db
from api.routes import auth, users, groups, plans, availability, availability_group, feedback, calendar, calendar_events


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    await db.connect()
    yield
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
app.include_router(calendar.router)
app.include_router(calendar_events.router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def root():
    return {"message": "Ketchup API", "docs": "/docs"}

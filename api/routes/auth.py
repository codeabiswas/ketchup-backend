"""Authentication routes."""
import bcrypt
from fastapi import APIRouter, HTTPException

from database import db
from models.schemas import (
    GoogleSigninRequest,
    GoogleSigninResponse,
    SignupRequest,
    SigninRequest,
    AuthResponse,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/signup", response_model=AuthResponse, status_code=201)
async def signup(body: SignupRequest):
    """Register a new user with email and password."""
    existing = await db.fetchrow(
        "SELECT id FROM users WHERE email = $1",
        body.email.strip().lower(),
    )
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    password_hash = bcrypt.hashpw(
        body.password.encode("utf-8"),
        bcrypt.gensalt(),
    ).decode("utf-8")
    name = (body.name or body.email.split("@")[0]).strip() or body.email.split("@")[0]

    row = await db.fetchrow(
        """
        INSERT INTO users (email, name, password_hash)
        VALUES ($1, $2, $3)
        RETURNING id, email, name
        """,
        body.email.strip().lower(),
        name,
        password_hash,
    )
    return AuthResponse(
        user_id=row["id"],
        email=row["email"],
        name=row["name"],
    )


@router.post("/signin", response_model=AuthResponse)
async def signin(body: SigninRequest):
    """Sign in with email and password."""
    row = await db.fetchrow(
        "SELECT id, email, name, password_hash FROM users WHERE email = $1",
        body.email.strip().lower(),
    )
    if not row or not row["password_hash"]:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    stored = row["password_hash"]
    if isinstance(stored, str):
        stored = stored.encode("utf-8")
    if not bcrypt.checkpw(body.password.encode("utf-8"), stored):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    return AuthResponse(
        user_id=row["id"],
        email=row["email"],
        name=row["name"],
    )


@router.post("/google-signin", response_model=GoogleSigninResponse)
async def google_signin(body: GoogleSigninRequest):
    """Create user on first Google sign-in, or return existing user (dev/OAuth)."""
    email = body.email.strip().lower()
    row = await db.fetchrow(
        "SELECT id, email, name FROM users WHERE email = $1",
        email,
    )
    if row:
        return GoogleSigninResponse(
            user_id=row["id"],
            email=row["email"],
            name=row["name"],
        )

    row = await db.fetchrow(
        """
        INSERT INTO users (email, name, google_id)
        VALUES ($1, $2, $3)
        RETURNING id, email, name
        """,
        email,
        body.name or body.email.split("@")[0],
        body.google_id,
    )
    return GoogleSigninResponse(
        user_id=row["id"],
        email=row["email"],
        name=row["name"],
    )

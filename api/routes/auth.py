# api/routes/auth.py

"""Authentication routes — Google OAuth only."""

from fastapi import APIRouter

from database import db
from models.schemas import GoogleSigninRequest, GoogleSigninResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/google-signin", response_model=GoogleSigninResponse)
async def google_signin(body: GoogleSigninRequest):
    """
    Create user on first Google sign-in, or return existing user.

    Called by Auth.js v5 in the JWT callback after Google OAuth completes.
    This ensures every Google-authenticated user has a corresponding row
    in our users table with a stable UUID.
    """
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

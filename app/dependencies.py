"""Shared FastAPI dependencies — auth, service injection, etc."""

from fastapi import Header, HTTPException

from app.config import settings


async def verify_api_key(x_api_key: str = Header(...)) -> str:
    """MVP auth: simple API key check via X-API-Key header.

    Phase 2 replaces this with Firebase Auth / JWT.
    """
    if x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key

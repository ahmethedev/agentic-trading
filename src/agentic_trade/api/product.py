"""Product API: public market discovery and protected operator reads."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import secrets
import time

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, SecretStr

from ..product.service import answer_question, market_overview, route_question, strategy, workspace

router = APIRouter(prefix="/api/product")
COOKIE = "tmq_operator"
ALLOWED_ORIGINS = {
    f"http://{host}:{port}"
    for host in ("localhost", "127.0.0.1")
    for port in (5173, 8010, 8011, 8002, 8000)
}
_attempts: dict[str, list[float]] = {}


def operator_token():
    return os.environ.get("APP_OPERATOR_TOKEN", "")


def authorised(request: Request):
    token = operator_token()
    cookie = request.cookies.get(COOKIE, "")
    if not token or not cookie:
        return False
    try:
        payload, sig = cookie.rsplit(".", 1)
        expiry, _nonce = payload.split(":", 1)
        expected = hmac.new(token.encode(), payload.encode(), hashlib.sha256).hexdigest()
        return int(expiry) > time.time() and hmac.compare_digest(sig, expected)
    except (ValueError, TypeError):
        return False


def require_operator(request: Request):
    if not authorised(request):
        raise HTTPException(401, "Hesap kayıtları için operatör oturumunu açın.")


class Login(BaseModel):
    token: SecretStr


class Question(BaseModel):
    message: str = Field(min_length=2, max_length=1000)
    inst_id: str | None = Field(default=None, pattern=r"^[A-Z0-9]{2,12}-USDT$")
    hours: int = Field(default=6, ge=1, le=48)


@router.get("/session")
async def session(request: Request):
    return {"authenticated": authorised(request), "configured": bool(operator_token())}


@router.post("/session")
async def login(body: Login, request: Request, response: Response):
    now = time.time()
    key = request.client.host if request.client else "local"
    times = [t for t in _attempts.get(key, []) if now - t < 60]
    _attempts[key] = times
    if len(times) >= 5:
        raise HTTPException(429, "Çok fazla deneme. Bir dakika sonra tekrar deneyin.")
    times.append(now)
    token = operator_token()
    if not token:
        raise HTTPException(503, "API sürecinde APP_OPERATOR_TOKEN yapılandırılmamış.")
    if not hmac.compare_digest(body.token.get_secret_value(), token):
        raise HTTPException(401, "Operatör erişim kodu geçersiz.")
    payload = f"{int(now) + 8 * 3600}:{secrets.token_hex(16)}"
    signature = hmac.new(token.encode(), payload.encode(), hashlib.sha256).hexdigest()
    response.set_cookie(
        COOKIE,
        f"{payload}.{signature}",
        httponly=True,
        samesite="strict",
        max_age=8 * 3600,
        secure=request.url.scheme == "https",
    )
    _attempts.pop(key, None)
    return {"authenticated": True}


@router.delete("/session")
async def logout(response: Response):
    response.delete_cookie(COOKIE)
    return {"authenticated": False}


@router.get("/market")
async def market():
    return await market_overview()


@router.get("/strategy")
async def get_strategy():
    return strategy()


@router.get("/workspace")
async def get_workspace(request: Request):
    require_operator(request)
    return await workspace()


@router.post("/ask")
async def ask(body: Question, request: Request):
    if route_question(body.message) not in ("get_market_overview", "get_strategy", "unsupported"):
        require_operator(request)
    try:
        async with asyncio.timeout(12):
            return await answer_question(body.message, body.inst_id, body.hours)
    except TimeoutError:
        raise HTTPException(
            504, "Veri sorgusu zaman aşımına uğradı. Soruyu tekrar deneyin."
        ) from None

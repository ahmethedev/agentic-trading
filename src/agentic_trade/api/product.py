"""Product API: public market discovery and protected operator reads."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, SecretStr

from ..config import get_settings
from ..product import experiments, llm
from ..product.service import answer_question, market_overview, route_question, strategy, workspace
from ..product.templates import DraftRejected

log = structlog.get_logger(__name__)

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


class Draft(BaseModel):
    """One catalogued rule change on a saved version. Never free-form JSON."""

    parent_version_id: int = Field(ge=1)
    key: str = Field(pattern=r"^(entry|exit)\.[a-z_]{3,40}$")
    value: float | None = None
    note: str = Field(default="", max_length=280)


class StartExperiment(BaseModel):
    version_id: int = Field(ge=1)
    mode: str = Field(pattern=r"^(SHADOW|REPLAY)$")


class Question(BaseModel):
    message: str = Field(min_length=2, max_length=1000)
    inst_id: str | None = Field(default=None, pattern=r"^[A-Z0-9]{2,12}-USDT$")
    hours: int = Field(default=6, ge=1, le=48)
    conversation_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")


# --- Conversation state -----------------------------------------------------
#
# Follow-up questions need the previous turns, and the model's own tool_use /
# tool_result blocks have to survive verbatim for the next request to be valid.
# They live in this process, not in PostgreSQL: the API's pools are read-only at
# the database level (a deliberate property -- the dashboard cannot write to the
# ledger), and opening a write path here to persist chat would give that up.
# The cost is that history is lost on restart, which the UI states plainly.


@dataclass
class Conversation:
    messages: list
    authorized: bool
    touched: float
    lock: asyncio.Lock


_conversations: dict[str, Conversation] = {}
CONVERSATION_TTL_S = 2 * 3600
MAX_CONVERSATIONS = 30


def conversation(conv_id: str | None, authorized: bool) -> tuple[str, Conversation]:
    """Fetch or open a conversation, evicting stale ones first.

    A conversation opened under an operator session carries account data in its
    history, so it is never continued by a request that is not authorised -- an
    unauthenticated caller with a guessed id gets a fresh conversation, not the
    contents of someone's ledger.
    """
    now = time.time()
    for key, conv in list(_conversations.items()):
        if now - conv.touched > CONVERSATION_TTL_S:
            del _conversations[key]
    existing = _conversations.get(conv_id) if conv_id else None
    if existing is not None and existing.authorized == authorized:
        existing.touched = now
        return conv_id, existing  # type: ignore[return-value]
    while len(_conversations) >= MAX_CONVERSATIONS:
        del _conversations[min(_conversations, key=lambda k: _conversations[k].touched)]
    new_id = secrets.token_hex(16)
    conv = Conversation(messages=[], authorized=authorized, touched=now, lock=asyncio.Lock())
    _conversations[new_id] = conv
    return new_id, conv


def _budget() -> float:
    settings = get_settings()
    return settings.llm_timeout_s + 5 if llm.available(settings) else 15


def require_scope(request: Request, message: str) -> None:
    """Account-scope questions need an operator session before anything runs.

    The model is separately barred from account tools when unauthorised
    (`tools.execute`); this keeps the cheap, explicit refusal at the edge, so an
    unauthenticated request never reaches the model or the ledger at all.
    """
    if route_question(message) not in ("get_market_overview", "get_strategy", "unsupported"):
        require_operator(request)


async def answer(body: Question, authorized: bool):
    """Run one question, yielding UI events and finally the whole answer.

    Falls back to the deterministic reader when the model is not configured or
    cannot be reached. The answer always says which engine produced it.
    """
    settings = get_settings()
    started = datetime.now(UTC)
    conv_id, conv = conversation(body.conversation_id, authorized)

    def envelope(**fields):
        return {
            "conversation_id": conv_id,
            "as_of": datetime.now(UTC).isoformat(),
            "duration_ms": round((datetime.now(UTC) - started).total_seconds() * 1000),
            "authorized": authorized,
            **fields,
        }

    if not llm.available(settings):
        result = await answer_question(body.message, body.inst_id, body.hours)
        yield {"type": "answer", "answer": envelope(**result, calls=[], usage=None)}
        return

    async with conv.lock:
        streamed = False
        try:
            events = llm.run(
                body.message,
                settings=settings,
                authorized=authorized,
                history=conv.messages,
                inst_id=body.inst_id,
                hours=body.hours,
            )
            async for event in events:
                if event["type"] == "text":
                    streamed = True
                    yield event
                elif event["type"] in ("tool", "text_reset"):
                    yield event
                elif event["type"] == "result":
                    result = event["result"]
                    conv.messages = llm.prune(result.messages)
                    conv.touched = time.time()
                    yield {
                        "type": "answer",
                        "answer": envelope(
                            text=result.text,
                            tool=result.calls[-1].name if result.calls else None,
                            data=None,
                            engine=f"anthropic:{settings.llm_model}",
                            model=settings.llm_model,
                            effort=(
                                settings.llm_effort
                                if llm.supports_effort(settings.llm_model)
                                else None
                            ),
                            turns=result.turns,
                            truncated=result.truncated,
                            stop_reason=result.stop_reason,
                            usage=result.usage.as_dict(),
                            calls=[asdict(c) for c in result.calls],
                            notice="Claude araçlarla kendi kayıtlarını okur; "
                            "sohbet geçmişi bu sunucu oturumunda tutulur.",
                        ),
                    }
                    return
        except llm.LLMUnavailable as exc:
            log.warning("chat_llm_unavailable", detail=str(exc))
        except Exception:
            log.warning("chat_llm_failed", exc_info=True)

        # The model dropped out. Answer from the deterministic reader rather
        # than showing the user nothing, and label the engine honestly.
        if streamed:
            yield {"type": "text_reset"}
        result = await answer_question(body.message, body.inst_id, body.hours)
        yield {
            "type": "answer",
            "answer": envelope(
                **result,
                calls=[],
                usage=None,
                fallback="Model cevabı alınamadı; sınırlı sorgu asistanına düşüldü.",
            ),
        }


@router.get("/session")
async def session(request: Request):
    return {
        "authenticated": authorised(request),
        "configured": bool(operator_token()),
        "assistant": llm.describe(get_settings()),
    }


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


# --- experiments ------------------------------------------------------------
#
# The only writing endpoints in the product API, and the write is narrow: a saved
# rule version, a simulated run, or the pair that joins two runs. None of them
# can reach the venue, the ledger or a live position, and all of them require an
# operator session.


@router.get("/experiments")
async def get_experiments(request: Request):
    require_operator(request)
    return await experiments.overview()


@router.post("/experiments/draft")
async def create_draft(body: Draft, request: Request):
    require_operator(request)
    try:
        return await experiments.create_draft(
            body.parent_version_id, body.key, body.value, body.note
        )
    except DraftRejected as exc:
        raise HTTPException(400, str(exc)) from None


@router.post("/experiments/start")
async def start_experiment(body: StartExperiment, request: Request):
    """Open the experiment, or return the one this version already has.

    Idempotent by request key, so a repeated click cannot open a second run
    (PRODUCT.md §10).
    """
    require_operator(request)
    try:
        started = await experiments.start_experiment(body.version_id, body.mode)
        return await experiments.experiment_status(started["experiment_id"], force=True) | {
            "created": started["created"]
        }
    except DraftRejected as exc:
        raise HTTPException(400, str(exc)) from None


@router.get("/experiments/{experiment_id}")
async def get_experiment(experiment_id: int, request: Request):
    require_operator(request)
    try:
        return await experiments.experiment_status(experiment_id)
    except DraftRejected as exc:
        raise HTTPException(404, str(exc)) from None


@router.post("/experiments/runs/{exp_run_id}/stop")
async def stop_experiment_run(exp_run_id: int, request: Request):
    """End a shadow observation. Nothing is closed at a venue: nothing was opened."""
    require_operator(request)
    return await experiments.stop_run(exp_run_id)


@router.post("/ask")
async def ask(body: Question, request: Request):
    """Answer a question and return it whole.

    Used by clients that cannot stream, and by the UI as the fallback path.
    """
    require_scope(request, body.message)
    events = answer(body, authorised(request))
    payload = None
    try:
        async with asyncio.timeout(_budget()):
            async for event in events:
                if event["type"] == "answer":
                    payload = event["answer"]
    except TimeoutError:
        await events.aclose()
        raise HTTPException(
            504, "Cevap zaman aşımına uğradı. Soruyu daraltıp tekrar deneyin."
        ) from None
    return payload


@router.post("/ask/stream")
async def ask_stream(body: Question, request: Request):
    """Same answer, delivered as it happens.

    The stage events are the real tool calls, not a simulated thought stream:
    the UI shows what is actually being read while it is being read
    (PRODUCT.md §13).
    """
    require_scope(request, body.message)
    authorized = authorised(request)

    async def sse():
        events = answer(body, authorized)
        try:
            async with asyncio.timeout(_budget()):
                async for event in events:
                    yield f"data: {json.dumps(event, default=str, ensure_ascii=False)}\n\n"
        except TimeoutError:
            await events.aclose()
            yield "data: " + json.dumps(
                {
                    "type": "failed",
                    "detail": "Cevap zaman aşımına uğradı. Soruyu daraltıp tekrar deneyin.",
                },
                ensure_ascii=False,
            ) + "\n\n"
        except Exception:
            log.warning("chat_stream_failed", exc_info=True)
            await events.aclose()
            yield "data: " + json.dumps(
                {"type": "failed", "detail": "Sohbet servisine ulaşılamadı."},
                ensure_ascii=False,
            ) + "\n\n"

    return StreamingResponse(
        sse(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )

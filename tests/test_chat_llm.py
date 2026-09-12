"""Ask My Quant: tool boundary, fallback and what reaches the model.

These run without an Anthropic key: the client is replaced by a scripted stub,
so the loop, the scope enforcement and the fallback are exercised deterministically.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from agentic_trade.api import product
from agentic_trade.api.main import app
from agentic_trade.config import Settings
from agentic_trade.product import llm, tools

ORIGIN = {"Origin": "http://localhost:8010"}


def settings(**overrides) -> Settings:
    base = {
        "DATABASE_URL": "postgresql://unused/unused",
        "ANTHROPIC_API_KEY": "sk-ant-test-not-a-real-key",
    }
    return Settings(**{**base, **overrides})  # type: ignore[arg-type]


# --- Stub Anthropic client --------------------------------------------------


@dataclass
class Block:
    type: str
    text: str = ""
    id: str = ""
    name: str = ""
    input: dict | None = None


@dataclass
class Usage:
    input_tokens: int = 100
    output_tokens: int = 20
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass
class Response:
    content: list[Block]
    stop_reason: str
    usage: Usage = None  # type: ignore[assignment]

    def __post_init__(self):
        self.usage = self.usage or Usage()


class Stream:
    def __init__(self, response: Response):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        response = self._response

        async def gen():
            for block in response.content:
                if block.type == "text":
                    yield Block(type="text", text=block.text)

        return gen()

    async def get_final_message(self):
        return self._response


class StubMessages:
    def __init__(self, responses: list[Response]):
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []

    def stream(self, **kwargs):
        # The caller keeps appending to its own message list, so snapshot it:
        # otherwise every recorded request points at the same mutated object.
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return Stream(self.responses.pop(0))


class StubClient:
    def __init__(self, responses: list[Response]):
        self.messages = StubMessages(responses)


def install(monkeypatch, responses: list[Response]) -> StubClient:
    stub = StubClient(responses)
    monkeypatch.setattr(llm, "_client", stub)
    return stub


async def collect(message: str, *, authorized: bool, cfg=None, history=None):
    events = []
    async for event in llm.run(
        message,
        settings=cfg or settings(),
        authorized=authorized,
        history=history,
    ):
        events.append(event)
    return events


# --- The model cannot reach account data without an operator session --------


async def test_operator_tools_hidden_without_session():
    public = {t["name"] for t in tools.schemas(authorized=False)}
    everything = {t["name"] for t in tools.schemas(authorized=True)}
    assert public == {"get_market_overview", "get_strategy"}
    assert {"get_risk_summary", "get_recent_fills", "get_decision_funnel"} <= everything


async def test_operator_tool_refused_even_when_named(monkeypatch):
    """Hiding a tool is not the enforcement; execute() refuses it as well."""
    called = AsyncMock()
    monkeypatch.setattr(tools, "workspace", called)
    ctx = tools.Context(authorized=False)
    payload, is_error = await tools.execute(ctx, "get_risk_summary", {})
    assert is_error
    assert "Operatör oturumu" in payload
    called.assert_not_awaited()


async def test_unknown_tool_and_bad_arguments_are_rejected():
    ctx = tools.Context(authorized=True)
    payload, is_error = await tools.execute(ctx, "place_order", {"inst_id": "BTC-USDT"})
    assert is_error and "Bilinmeyen araç" in payload
    payload, is_error = await tools.execute(ctx, "get_strategy", {"drop_table": 1})
    assert is_error and "Geçersiz parametre" in payload


# --- The loop ----------------------------------------------------------------


async def test_tool_loop_runs_tool_then_answers(monkeypatch):
    monkeypatch.setattr(
        tools,
        "strategy",
        lambda: {"version": "retail_baseline_v1", "rules": ["kural"]},
    )
    stub = install(
        monkeypatch,
        [
            Response(
                content=[
                    Block(type="text", text="Bakıyorum."),
                    Block(type="tool_use", id="t1", name="get_strategy", input={}),
                ],
                stop_reason="tool_use",
            ),
            Response(
                content=[Block(type="text", text="Stratejin reclaim kuralıyla çalışıyor.")],
                stop_reason="end_turn",
            ),
        ],
    )
    events = await collect("Stratejim nasıl çalışıyor?", authorized=False)
    kinds = [e["type"] for e in events]
    assert "tool" in kinds and "text_reset" in kinds
    result = events[-1]["result"]
    assert result.text == "Stratejin reclaim kuralıyla çalışıyor."
    assert [c.name for c in result.calls] == ["get_strategy"]
    assert result.calls[0].ok
    assert result.turns == 2
    assert result.usage.input_tokens == 200

    # The tool result carried the real service payload back to the model.
    follow_up = stub.messages.requests[1]["messages"]
    tool_result = follow_up[-1]["content"][0]
    assert follow_up[-1]["role"] == "user"
    assert tool_result["tool_use_id"] == "t1"
    assert json.loads(tool_result["content"])["version"] == "retail_baseline_v1"
    assert "is_error" not in tool_result


async def test_failing_tool_is_reported_not_invented(monkeypatch):
    async def boom():
        raise RuntimeError("relation does not exist")

    monkeypatch.setattr(tools, "market_overview", boom)
    install(
        monkeypatch,
        [
            Response(
                content=[Block(type="tool_use", id="t1", name="get_market_overview", input={})],
                stop_reason="tool_use",
            ),
            Response(
                content=[Block(type="text", text="Piyasa verisini okuyamadım.")],
                stop_reason="end_turn",
            ),
        ],
    )
    events = await collect("Piyasanın fotoğrafını çıkar", authorized=False)
    result = events[-1]["result"]
    assert result.calls[0].ok is False
    end = next(e for e in events if e["type"] == "tool" and e["phase"] == "end")
    assert end["ok"] is False


async def test_turn_budget_stops_a_looping_model(monkeypatch):
    monkeypatch.setattr(tools, "strategy", lambda: {"version": "v"})
    loop_forever = [
        Response(
            content=[Block(type="tool_use", id=f"t{i}", name="get_strategy", input={})],
            stop_reason="tool_use",
        )
        for i in range(5)
    ]
    install(monkeypatch, loop_forever)
    events = await collect(
        "Stratejim nasıl çalışıyor?", authorized=False, cfg=settings(LLM_MAX_TURNS=2)
    )
    result = events[-1]["result"]
    assert result.turns == 2
    assert result.truncated
    assert len(result.calls) == 2


async def test_effort_is_sent_only_to_models_that_accept_it(monkeypatch):
    """Haiku 4.5 rejects output_config.effort with a 400; Opus takes it."""
    monkeypatch.setattr(tools, "strategy", lambda: {"version": "v"})
    stub = install(
        monkeypatch,
        [Response(content=[Block(type="text", text="Cevap.")], stop_reason="end_turn")],
    )
    await collect("Piyasa nasıl?", authorized=False, cfg=settings(LLM_MODEL="claude-haiku-4-5"))
    assert "output_config" not in stub.messages.requests[0]
    assert stub.messages.requests[0]["model"] == "claude-haiku-4-5"

    stub = install(
        monkeypatch,
        [Response(content=[Block(type="text", text="Cevap.")], stop_reason="end_turn")],
    )
    await collect(
        "Piyasa nasıl?",
        authorized=False,
        cfg=settings(LLM_MODEL="claude-opus-5", LLM_EFFORT="high"),
    )
    assert stub.messages.requests[0]["output_config"] == {"effort": "high"}


async def test_prompt_carries_no_secret(monkeypatch):
    monkeypatch.setattr(tools, "strategy", lambda: {"version": "v"})
    stub = install(
        monkeypatch,
        [Response(content=[Block(type="text", text="Cevap.")], stop_reason="end_turn")],
    )
    cfg = settings(
        OKX_API_KEY="canary-okx-key",
        OKX_API_SECRET="canary-okx-secret",
        OKX_API_PASSPHRASE="canary-passphrase",
        ANTHROPIC_API_KEY="canary-anthropic-key",
        DATABASE_URL="postgresql://canary-user:canary-db-password@127.0.0.1:5433/at",
    )
    await collect("Piyasa nasıl?", authorized=True, cfg=cfg)
    sent = json.dumps(stub.messages.requests[0], default=str)
    for secret in (
        "canary-okx-key",
        "canary-okx-secret",
        "canary-passphrase",
        "canary-anthropic-key",
        "canary-db-password",
    ):
        assert secret not in sent


async def test_history_prune_keeps_tool_pairs_intact():
    history = [
        {"role": "user", "content": "ilk soru"},
        {"role": "assistant", "content": [Block(type="tool_use", id="t1", name="x")]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1"}]},
        {"role": "assistant", "content": [Block(type="text", text="cevap")]},
        {"role": "user", "content": "ikinci soru"},
        {"role": "assistant", "content": [Block(type="text", text="cevap 2")]},
    ]
    kept = llm.prune(history, keep=4)
    assert kept[0] == {"role": "user", "content": "ikinci soru"}
    assert not any(
        isinstance(m["content"], list)
        and any(getattr(b, "type", None) == "tool_use" for b in m["content"])
        for m in kept
    )


# --- Endpoint behaviour ------------------------------------------------------


async def test_falls_back_to_reader_when_model_unavailable(monkeypatch):
    monkeypatch.setattr(product, "get_settings", lambda: settings())
    monkeypatch.setattr(
        llm,
        "run",
        lambda *a, **k: _raise_unavailable(),
    )
    monkeypatch.setattr(
        product,
        "answer_question",
        AsyncMock(return_value={"text": "okuyucu cevabı", "tool": "get_strategy", "data": None}),
    )
    body = product.Question(message="Stratejim nasıl çalışıyor?")
    events = [e async for e in product.answer(body, authorized=False)]
    answer = events[-1]["answer"]
    assert answer["text"] == "okuyucu cevabı"
    assert "sınırlı sorgu asistanına düşüldü" in answer["fallback"]


async def _raise_unavailable():
    raise llm.LLMUnavailable("no key")
    yield  # pragma: no cover - generator form


async def test_reader_is_used_when_no_key_configured(monkeypatch):
    monkeypatch.setattr(product, "get_settings", lambda: settings(ANTHROPIC_API_KEY=None))
    monkeypatch.setattr(
        product,
        "answer_question",
        AsyncMock(return_value={"text": "okuyucu", "tool": None, "data": None}),
    )
    body = product.Question(message="Piyasa nasıl?")
    events = [e async for e in product.answer(body, authorized=False)]
    assert events[-1]["answer"]["text"] == "okuyucu"
    assert "fallback" not in events[-1]["answer"]


async def test_conversation_is_not_shared_across_authorisation(monkeypatch):
    product._conversations.clear()
    operator_id, operator_conv = product.conversation(None, authorized=True)
    operator_conv.messages = [{"role": "user", "content": "hesap verisi"}]
    guest_id, guest_conv = product.conversation(operator_id, authorized=False)
    assert guest_id != operator_id
    assert guest_conv.messages == []


async def test_stream_endpoint_emits_stages_then_answer(monkeypatch):
    monkeypatch.setenv("APP_OPERATOR_TOKEN", "")
    monkeypatch.setattr(product, "get_settings", lambda: settings())
    monkeypatch.setattr(tools, "strategy", lambda: {"version": "retail_baseline_v1"})
    install(
        monkeypatch,
        [
            Response(
                content=[Block(type="tool_use", id="t1", name="get_strategy", input={})],
                stop_reason="tool_use",
            ),
            Response(
                content=[Block(type="text", text="Kuralların şöyle.")],
                stop_reason="end_turn",
            ),
        ],
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8010") as c:
        response = await c.post(
            "/api/product/ask/stream",
            json={"message": "Stratejim nasıl çalışıyor?"},
            headers=ORIGIN,
        )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]
    stages = [e["stage"] for e in events if e["type"] == "tool" and e["phase"] == "start"]
    assert stages == ["Strateji sürümü okunuyor"]
    answer = next(e["answer"] for e in events if e["type"] == "answer")
    assert answer["text"] == "Kuralların şöyle."
    assert answer["engine"] == "anthropic:claude-haiku-4-5"
    assert answer["calls"][0]["name"] == "get_strategy"
    assert answer["conversation_id"]


@pytest.mark.parametrize(
    "message",
    ["Bugün ne kadar risk aldık?", "Son işlemi neden aldık?", "Neden işlem açmadık?"],
)
async def test_account_questions_still_require_operator_session(monkeypatch, message):
    monkeypatch.setenv("APP_OPERATOR_TOKEN", "canary-operator-secret")
    monkeypatch.setattr(product, "get_settings", lambda: settings())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8010") as c:
        for path in ("/api/product/ask", "/api/product/ask/stream"):
            response = await c.post(path, json={"message": message}, headers=ORIGIN)
            assert response.status_code == 401


# --- Output the chat panel can actually render -------------------------------


def test_markdown_is_stripped_because_the_panel_prints_text():
    assert llm.plain("**BTC** güçlü") == "BTC güçlü"
    assert llm.plain("__ETH__ zayıf") == "ETH zayıf"
    assert llm.plain("## Başlık\ngövde") == "Başlık\ngövde"
    assert llm.plain("`rvol` 1,3") == "rvol 1,3"
    # Ordinary text, including lone asterisks in prose, survives unchanged.
    assert llm.plain("risk %1 · stop 101,76 USDT") == "risk %1 · stop 101,76 USDT"


def test_streamed_fragments_lose_markers_even_when_split():
    assert llm.plain_delta("**BTC") + llm.plain_delta("USDT**") == "BTCUSDT"


async def test_answer_text_is_plain(monkeypatch):
    monkeypatch.setattr(tools, "strategy", lambda: {"version": "v"})
    install(
        monkeypatch,
        [
            Response(
                content=[Block(type="text", text="**Sonuç:** hacim 1,3 · `rvol` düşük")],
                stop_reason="end_turn",
            )
        ],
    )
    events = await collect("Piyasa nasıl?", authorized=False)
    assert events[-1]["result"].text == "Sonuç: hacim 1,3 · rvol düşük"

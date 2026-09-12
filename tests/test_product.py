"""Product boundaries and real run isolation, including paper/test contamination."""

from unittest.mock import AsyncMock

import httpx
import pytest
from conftest import requires_db

from agentic_trade.api import product
from agentic_trade.api.main import app
from agentic_trade.db import pool
from agentic_trade.product import service


@pytest.mark.parametrize(
    ("message", "tool"),
    [
        ("Piyasanın fotoğrafını çıkar", "get_market_overview"),
        ("Neden işlem açmadık?", "explain_wait"),
        ("BTC neden bekliyor?", "explain_wait"),
        ("Son işlemi neden aldık?", "last_trade"),
        ("Stratejim nasıl çalışıyor?", "get_strategy"),
        ("Bugün maliyetimiz ne?", "get_risk_summary"),
        ("Bu stratejiyi kopyala ve gölge başlat", "unsupported"),
        ("Limitleri değiştir ve emir ver", "unsupported"),
        ("Bana hava durumunu söyle", "unsupported"),
    ],
)
def test_question_scope(message, tool):
    assert service.route_question(message) == tool


async def test_operator_boundary(monkeypatch):
    monkeypatch.setenv("APP_OPERATOR_TOKEN", "canary-operator-secret")
    product._attempts.clear()
    mock = AsyncMock(return_value={"run": None})
    monkeypatch.setattr(product, "workspace", mock)
    monkeypatch.setattr(product, "answer_question", AsyncMock(return_value={"text": "answer"}))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8010") as c:
        assert (await c.get("/api/product/workspace")).status_code == 401
        assert (await c.get("/api/positions")).status_code == 401
        assert (await c.get("/api/status")).status_code == 401
        body = {"message": "Neden işlem açmadık?"}
        headers = {"Origin": "http://localhost:8010"}
        assert (await c.post("/api/product/ask", json=body, headers=headers)).status_code == 401
        assert (await c.post("/api/product/ask", json=body)).status_code == 403
        assert (
            await c.post(
                "/api/product/session",
                json={"token": "canary-operator-secret"},
                headers={"Origin": "https://evil.example"},
            )
        ).status_code == 403
        r = await c.post(
            "/api/product/session", json={"token": "canary-operator-secret"}, headers=headers
        )
        assert r.status_code == 200
        assert "HttpOnly" in r.headers["set-cookie"]
        assert "SameSite=strict" in r.headers["set-cookie"]
        assert "canary-operator-secret" not in r.text + r.headers["set-cookie"]
        assert (await c.get("/api/product/workspace")).status_code == 200
        assert (
            await c.get("/api/product/workspace", headers={"Host": "evil.example"})
        ).status_code == 400
        assert (
            await c.get("/api/product/workspace", headers={"Origin": "https://evil.example"})
        ).status_code == 403
        monkeypatch.setenv("APP_OPERATOR_TOKEN", "rotated-secret")
        assert (await c.get("/api/product/workspace")).status_code == 401
    mock.assert_awaited_once()


async def test_unknown_question_never_claims_action():
    result = await service.answer_question("Gölge başlat", None, 6)
    assert result["tool"] == "unsupported"
    assert result["data"] is None
    assert "henüz bağlı değil" in result["text"]


async def test_no_decisions_is_not_market_selectivity(monkeypatch):
    monkeypatch.setattr(
        service,
        "workspace",
        AsyncMock(
            return_value={
                "run": {"run_id": 7},
                "funnel": {
                    "evaluations": 0,
                    "unique_candles": 0,
                    "episodes": 0,
                    "confirmed": 0,
                    "codes": [],
                },
            }
        ),
    )
    result = await service.answer_question("Neden işlem açmadık?", None, 6)
    assert "karar kaydı yok" in result["text"]
    assert "risk ve emir aşamasına geçilmemiş" not in result["text"]


@requires_db
@pytest.mark.asyncio(loop_scope="session")
async def test_run_isolation_and_unique_candles(run_id):
    async with pool.ledger().acquire() as con:
        await con.execute(
            "UPDATE runs SET mode='live', code_version='test-worker' WHERE run_id=$1", run_id
        )
        other = await con.fetchval("""INSERT INTO runs (mode,site,demo,policy_version)
            VALUES ('paper','tr',true,'test') RETURNING run_id""")
        await con.execute(
            """INSERT INTO decisions
            (run_id,inst_id,action,stage_reached,reason_codes,features,policy_version,
             data_quality,candle_open_time)
            SELECT $1,'BTC-USDT','WAIT','CONFIRM_REJECTED',ARRAY['RVOL_TOO_LOW'],
                   '{}','retail_baseline_v1','{}',date_trunc('hour',now())
            FROM generate_series(1,4)""",
            run_id,
        )
        await con.execute(
            """INSERT INTO decisions
            (run_id,inst_id,action,stage_reached,features,policy_version,data_quality)
            VALUES ($1,'ETH-USDT','WAIT','NO_SETUP','{}','test','{}')""",
            other,
        )
    try:
        result = await service.workspace()
        assert result["run"]["run_id"] == run_id
        assert result["funnel"]["evaluations"] == 4
        assert result["funnel"]["unique_candles"] == 1
        assert result["ledger"]["fills"] == []
        assert result["ledger"]["open_positions"] == 0
        assert all(d["run_id"] == run_id for d in result["decisions"])
    finally:
        async with pool.ledger().acquire() as con:
            await con.execute("DELETE FROM decisions WHERE run_id=$1", other)
            await con.execute("DELETE FROM runs WHERE run_id=$1", other)


async def test_confirmed_wait_explains_risk_gate_before_history(monkeypatch):
    monkeypatch.setattr(
        service,
        "workspace",
        AsyncMock(
            return_value={
                "run": {"run_id": 7},
                "funnel": {
                    "evaluations": 20,
                    "unique_candles": 2,
                    "episodes": 1,
                    "confirmed": 1,
                    "codes": [
                        {"code": "RVOL_TOO_LOW", "label": "Hacim yetersiz", "evaluations": 19},
                        {
                            "code": "ENTRY_BUDGET_EXHAUSTED",
                            "label": "Giriş hakkı kullanıldı",
                            "evaluations": 1,
                        },
                    ],
                },
            }
        ),
    )
    result = await service.answer_question("Neden işlem açmadık?", None, 6)
    assert "Onaydan sonraki engeller: Giriş hakkı kullanıldı (1)" in result["text"]


@requires_db
@pytest.mark.asyncio(loop_scope="session")
async def test_public_market_redacts_private_sizing_and_gate(run_id):
    import json

    async with pool.ledger().acquire() as con:
        await con.execute(
            "UPDATE runs SET mode='live',code_version='test-worker' WHERE run_id=$1", run_id
        )
        inserted = await con.fetchval("""INSERT INTO instruments
            (venue,inst_id,base_ccy,quote_ccy,tick_sz,lot_sz,min_sz,state)
            VALUES ('okx-tr','TEST-USDT','TEST','USDT',0.1,0.1,1,'live')
            ON CONFLICT DO NOTHING RETURNING inst_id""")
        await con.execute(
            """INSERT INTO decisions
            (run_id,inst_id,action,stage_reached,reason_codes,features,policy_version,data_quality)
            VALUES ($1,'TEST-USDT','WAIT','CONFIRMED',
            ARRAY['RECLAIM_CONFIRMED','CONCURRENCY_LIMIT'],
            '{"rvol":1.4,"sizing":{"equity":"canary-private-balance"}}','test','{}')""",
            run_id,
        )
    try:
        result = await service.market_overview()
        raw = json.dumps(result, default=str)
        assert "canary-private-balance" not in raw
        assert "CONCURRENCY_LIMIT" not in raw
        assert any(i["features"].get("rvol") == 1.4 for i in result["instruments"])
    finally:
        if inserted:
            async with pool.ledger().acquire() as con:
                await con.execute("DELETE FROM instruments WHERE inst_id='TEST-USDT'")

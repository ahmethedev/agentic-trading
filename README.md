# ThatsMyQuant

> An explainable, safety-first spot trading agent and personal quant workspace for OKX TR.

ThatsMyQuant turns a trading idea into a traceable system: it ingests market data,
detects setups, applies deterministic risk rules, records every decision, and exposes the
result through a React dashboard and a read-only AI analyst.

The project was built for the OKX Agentic Trading Hackathon and is now preserved as a
portfolio project and engineering reference. The interface is currently in Turkish.

> [!CAUTION]
> This is experimental software, not financial advice. `MODE=live` can place real orders.
> Start with `observe` or `paper`, use a dedicated sub-account, and review the code and
> exchange permissions before enabling live trading.

## Why this project exists

Most trading bots show the final order and hide the path that produced it. ThatsMyQuant
makes that path the product. Every evaluation—including every `WAIT`—is persisted with its
inputs, stage, reason codes, policy version, and data-quality state. A decision can therefore
be reconstructed from the database without asking a model to recreate the past.

The result combines three ideas:

- **Explainable automation:** scanner → setup → confirmation → risk → intent → order → fill
  is a queryable funnel, not a black box.
- **Deterministic safety:** the model can explain records, but it cannot size a position,
  bypass the risk gate, or reach an exchange write tool.
- **Evidence-driven iteration:** a strategy can be cloned with one rule change and compared
  in `SHADOW` or `REPLAY` mode without allocating capital.

## Product tour

The dashboard brings the operating record into one workspace:

- Market overview with candles, volume, spread, order-flow health, and data freshness
- Strategy cards showing rules, version, latest evaluation, and concrete `WAIT` reasons
- Decision funnel and live ledger views for intents, orders, fills, fees, and open risk
- **Ask My Quant**, an optional Anthropic-backed analyst with six bounded, read-only tools
- Deterministic backtests over recorded setup candidates and closed 5-minute candles
- A one-change experiment lab for baseline-vs-variant `SHADOW` and `REPLAY` comparisons
- Operator-session protection for private account data; public market discovery needs no key

Ask My Quant falls back to a deterministic reader when no model key is configured. Risk and
PnL are computed by application services—not by the language model—and each model answer
shows the tool trace that supported it.

## Architecture

```text
                                 ┌───────────────────────────────┐
                                 │ React + Vite workspace        │
                                 │ market · journal · experiments│
                                 └──────────────┬────────────────┘
                                                │ HTTP / SSE
                                 ┌──────────────▼────────────────┐
                                 │ FastAPI                        │
                                 │ read APIs · operator session   │
                                 │ bounded analyst tools          │
                                 └──────────────┬────────────────┘
                                                │
┌──────────┐   MCP over stdio   ┌───────────────▼───────────────┐
│ OKX TR   │◄──────────────────►│ Python worker                  │
│ Spot API │   OKX Agent Trade  │ ingest · features · strategy  │
└──────────┘   Kit              │ risk · execution · reconcile  │
                                └───────────────┬───────────────┘
                                                │
                                 ┌──────────────▼────────────────┐
                                 │ PostgreSQL                     │
                                 │ market · decisions · ledger    │
                                 │ strategy versions · experiments│
                                 └───────────────────────────────┘
```

| Layer | Technology |
|---|---|
| Exchange integration | `@okx_ai/okx-trade-mcp` 1.4.6, pinned and allowlisted |
| Worker | Python 3.12, asyncio, Pydantic, Decimal |
| Storage | PostgreSQL 17 |
| API | FastAPI with server-sent events for chat |
| Frontend | React 18, Vite, Lightweight Charts, Recharts |
| Verification | pytest, Ruff, fault-injecting paper venue |

## Safety and failure handling

The interesting part of this repository is not the entry signal; it is the boundary around
the signal.

- `observe`, `paper`, and `live` share the same decision path, while only `live` can reach
  exchange write calls.
- The ATK session exposes a code-enforced allowlist rather than trusting module selection.
- Position size is calculated from equity, stop distance, fees, available quote balance,
  venue lot size, minimum size, and a hard risk ceiling.
- Intents and reservations are durable before an order is sent, preventing duplicate entries
  across retries and concurrent evaluations.
- A write timeout becomes `UNKNOWN`; the worker queries venue state instead of blindly
  resending an order.
- Startup reconciliation blocks new entries until the ledger and venue agree.
- A watchdog continuously checks venue-side protection, re-arms missing OCO orders, ingests
  externally triggered exit fills, and closes unsellable dust without inventing PnL.
- Missing or gapped market data invalidates the affected signal. It is never treated as
  neutral evidence.
- Exchange credentials remain in the worker environment. The browser receives neither
  credentials nor a route to trading tools.

These controls were developed against a paper venue that can simulate rejections, partial
fills, delayed acknowledgements, timeouts, missing protection, and restart recovery.

## Strategy and experiment model

The reference strategy looks for a level reclaim after a pullback in a supportive market
context. Confirmation uses closed candles, relative volume, close location, and buyer-side
flow. The exact thresholds are versioned and stored with every decision.

Experiments deliberately change one supported rule at a time:

1. Clone the immutable baseline version.
2. Change one catalogued entry or exit parameter.
3. Run both legs with the same simulation assumptions.
4. Compare closed observations, fees, drawdown, profit factor, and evidence sufficiency.

`REPLAY` evaluates an archived window; `SHADOW` observes candidates recorded after the run
starts. Simulated results are never presented as live fills, unresolved trades are excluded
from win/loss statistics, and ambiguous same-candle stop/target events use the conservative
outcome.

## Getting started

### Prerequisites

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/)
- Node.js 20+ and npm
- PostgreSQL 15+ (17 recommended)
- `psql` and `createdb`

OKX credentials are optional in `observe` mode. Without them, the worker can ingest public
market data but uses placeholder account context, so sizing is indicative only.

### 1. Install dependencies

```bash
uv venv
uv pip install -e ".[dev]"
npm ci --prefix vendor/atk
npm ci --prefix dashboard
```

### 2. Create the database

```bash
createdb agentic_trade
psql postgresql://localhost/agentic_trade \
  -f src/agentic_trade/db/schema.sql
```

If your PostgreSQL user, password, host, or port differs, adjust the DSN accordingly.

### 3. Configure the environment

Create a git-ignored `.env` in the repository root:

```dotenv
DATABASE_URL=postgresql://localhost/agentic_trade

# Safe default: records decisions and never sends an order.
MODE=observe
OKX_SITE=tr
OKX_DEMO=false

INSTRUMENTS=BTC-USDT,ETH-USDT,SOL-USDT
ENTRY_INSTRUMENTS=
RISK_FRACTION=0.01
RISK_FRACTION_MAX=0.02
MAX_CONCURRENT_POSITIONS=1
MAX_POSITION_FRACTION=0.25
MAX_ENTRIES_PER_RUN=1

# Optional: enables the model-backed Ask My Quant flow.
ANTHROPIC_API_KEY=
LLM_MODEL=claude-haiku-4-5

# Optional in observe mode; required together for authenticated/live access.
OKX_API_KEY=
OKX_API_SECRET=
OKX_API_PASSPHRASE=
```

`APP_OPERATOR_TOKEN` is intentionally read from the API process environment rather than the
frontend. Generate one with `openssl rand -hex 24`; never expose it as a Vite variable.

### 4. Run the workspace

Open three terminals:

```bash
# Terminal 1 — market ingestion and decision worker
PYTHONPATH=src .venv/bin/python -m agentic_trade.worker

# Terminal 2 — API
export APP_OPERATOR_TOKEN="replace-with-the-generated-value"
PYTHONPATH=src .venv/bin/uvicorn agentic_trade.api.main:app \
  --host 127.0.0.1 --port 8010

# Terminal 3 — dashboard
npm run dev --prefix dashboard
```

Then open [http://localhost:5173](http://localhost:5173).

To exercise the complete execution state machine without sending exchange orders:

```bash
.venv/bin/python scripts/paper_demo.py
```

## Verification

Most execution and reconciliation tests use a real PostgreSQL database because the critical
invariants live in transactions and constraints. Use a dedicated scratch database—never a
ledger containing real trading history.

```bash
createdb agentic_trade_test
psql postgresql://localhost/agentic_trade_test \
  -f src/agentic_trade/db/schema.sql

DATABASE_URL=postgresql://localhost/agentic_trade_test \
  .venv/bin/python -m pytest tests/ -q

.venv/bin/ruff check src tests
npm run build --prefix dashboard
```

The test guard refuses to run destructive integration fixtures against a database containing
live fills or positions unless it is explicitly overridden.

## Repository map

```text
src/agentic_trade/
├── atk/          # long-lived MCP client and tool allowlist
├── ingest/       # trades, candles, order book, gap detection
├── features/     # deterministic market features
├── strategy/     # setup state machine and reason codes
├── risk/         # sizing and admission gates
├── execution/    # intent, order, fill, position, protection, reconciliation
├── product/      # dashboard services, analyst tools, simulations, experiments
├── api/          # FastAPI routes and operator boundary
└── db/           # schema and connection pools

dashboard/        # React workspace
tests/            # unit, integration, and end-to-end failure scenarios
docs/             # implementation notes and ATK integration evidence
```

Further reading:

- [System design and invariants](AGENT.md)
- [Product direction](PRODUCT.md)
- [ATK integration evidence](docs/ATK_INTEGRATION_EVIDENCE.md)

## Current limitations

- Market trades are polled through the pinned ATK connector; there is no WebSocket feed.
  High-volume bursts can overrun a page, so overlapping flow windows are marked invalid.
- The live worker currently protects the full position with venue-side OCO. The staged exit
  ladder is implemented and tested in simulation but is not driven by the live worker loop.
- The app is designed as a local, single-operator workspace. Its host/origin policy and
  session model are not a public multi-user deployment boundary.
- Backtests re-evaluate setup candidates already discovered and stored by the worker; they
  are not a general historical market scanner or a claim of profitable performance.
- Deployment scripts reflect the original private VPS environment and are reference material,
  not a turnkey public hosting configuration.

## Project status

The hackathon build is complete. This repository is maintained as a portfolio project: the
default mode is intentionally safe, the implementation is testable locally, and known limits
are documented rather than hidden. There is no public hosted trading service.

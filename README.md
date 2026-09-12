# agentic-trade

Spot trading agent for OKX TR built on the mandatory OKX Agent Trade Kit (ATK).
Records every decision — including every WAIT and its reason — so the funnel from
market data to fill is reconstructable from the database alone.

Design source: [AGENT.md](AGENT.md). Active policy profile: `retail_baseline_v1`.

> Status: **Deployed to the VPS in `observe` mode, collecting data.** Gate 1 (see)
> and Gate 2 (control) built. The full chain
> decision → intent → reservation → order → fill → position → protection runs and is
> tested against a fault-injecting paper venue. Live trading is blocked only by
> funding: **the competition sub-account holds no balance yet.**

## Architecture

```
OKX TR ──ATK MCP (stdio, long-lived)──► ingest ──► PostgreSQL ──► FastAPI ──► React
                                          │                         (read-only)
                                          ▼
                              features ──► setup detection ──► risk sizing ──► decision
```

| Layer | Choice |
|---|---|
| Exchange access | `@okx_ai/okx-trade-mcp` 1.4.6, pinned in `vendor/atk`, `OKX_SITE=tr` |
| Worker | Python 3.12 + asyncio, single owner of the ATK session |
| Store | PostgreSQL 17 (VPS container `agentic-trade-db`, localhost-bound) |
| API | FastAPI, read-only |
| Dashboard | React + Vite + Lightweight Charts |

## Setup

```bash
uv venv && uv pip install -e ".[dev]"      # python deps
(cd vendor/atk && npm install)             # pinned ATK
(cd dashboard && npm install)              # dashboard deps
./scripts/db-tunnel.sh up                  # ssh tunnel to the VPS Postgres
psql "$DATABASE_URL" -f src/agentic_trade/db/schema.sql   # idempotent
```

`.env` (git-ignored) needs:

```
OKX_API_KEY=...
OKX_API_SECRET=...
OKX_API_PASSPHRASE=...        # REQUIRED -- see Known gaps
DATABASE_URL=postgresql://agentic:...@127.0.0.1:5433/agentic_trade
MODE=observe                  # observe | paper | live
```

## Run

```bash
./scripts/db-tunnel.sh up                                    # DB tunnel
PYTHONPATH=src .venv/bin/python -m agentic_trade.worker      # ingest + decide
PYTHONPATH=src .venv/bin/uvicorn agentic_trade.api.main:app --port 8010
(cd dashboard && npm run dev)                                # http://localhost:5173
.venv/bin/python scripts/paper_demo.py                       # full chain, paper

DATABASE_URL=... .venv/bin/python -m pytest tests/ -q        # 62 tests
.venv/bin/ruff check src/ tests/
```

`MODE` controls the order path: `observe` never sends an order, `paper` runs the
identical state machine against a simulated venue, `live` sends real orders. The
tests cover `observe` and `paper`; `live` has never been exercised.

## Deploy

```bash
./scripts/deploy.sh          # build dashboard, rsync, rebuild image, restart
./scripts/db-tunnel.sh up    # localhost:5433 -> db, localhost:8002 -> dashboard
```

Runs as three containers in one compose project on the VPS (`db`, `worker`, `api`),
sharing a network so the worker reaches Postgres as `db:5432` with no tunnel. The
image carries both runtimes: Python for the trading logic, Node for the ATK MCP
server the worker spawns. Nothing is published publicly — the API is bound to
`127.0.0.1:8002` and reached over SSH.

Secrets live in `~/agentic-trade/.env.app` on the VPS (mode 600), never in the image
or the repo.

**Only one worker may run against this database.** It is the single owner of the
order path; a second worker would double-poll and, in `live`, contend for the same
inventory. `scripts/deploy.sh` does not stop a local worker — do that yourself.

### Sizing at 30 USDT (measured 12 Sep)

| Stop | Qty (BTC) | Notional | Realised risk | Capped by |
|---|---|---|---|---|
| −0.5% | 0.00038706 | 29.96 | 0.2395 / 0.30 | `SPOT_BALANCE`, `LOT_STEP` |
| −1.0% | 0.00029829 | 23.09 | 0.2999 / 0.30 | `LOT_STEP` |
| −2.0% | 0.00016861 | 13.05 | 0.2999 / 0.30 | `LOT_STEP` |

Every ladder leg clears the venue minimum on all three pairs — the smallest, a 10%
runner at a −2% stop, is ~1.3 USDT against a 0.77 USDT minimum for BTC. OKX spot
enforces `minSz` in base only; there is no separate minimum notional field.

Two consequences of the small account, neither of them a defect but both worth
stating plainly:

* **Fee drag is material.** A round trip on 23 USDT notional costs ~0.046 USDT at
  10 bps taker each way, against a 0.30 USDT risk budget — about **0.15R per round
  trip**. A nominal +2.5R gross outcome nets closer to +2.35R.
* **Tight stops under-risk.** At a −0.5% stop the position needs more notional than
  30 USDT supports, so quantity is capped by balance and realised risk lands at
  0.24 rather than 0.30. That is the intended behaviour — the stop is never widened
  to spend the budget — but it means the effective risk taken varies with stop width.

## Verified against the live venue

Measured, not assumed — all on OKX TR (`tr.okx.com`) on 12 Sep 2026:

| Question | Finding |
|---|---|
| Does ATK reach OKX TR? | Yes. `OKX_SITE=tr` → `market_get_ticker` returns live BTC-USDT. |
| Native protection? | Yes. `spot_place_order` takes attached `tpTriggerPx`/`slTriggerPx`; `spot_place_algo_order` supports **OCO**. |
| WebSocket / streaming? | **No.** Zero `wss://` or `WebSocket` references in the 1.4.6 bundle. REST polling only. |
| Is polled order flow usable? | Conditionally — see *Burst limitation* below. On a calm tape `market_get_trades` returns 500 prints spanning 283–531s, comfortably covering a 60s flow window. During a book sweep it does not. |
| Can trade loss be detected? | Yes. `tradeId` is contiguous and monotonic → dedup and gap detection by id, not by guesswork. Verified in DB: `id_span == distinct_ids == row_count`. |
| Closed-candle flag? | Yes. `confirm` is field 9 of `market_get_candles` (`"1"` closed). DB shows exactly 99 closed + 1 forming per series. |
| Tool surface | 168 tools with `--modules all`. We start with `market,spot,account` only (no swap/futures/option) **and** enforce a 20-tool allowlist in code. |

### Account (verified 12 Sep 2026, authenticated)

| Field | Value |
|---|---|
| uid / mainUid | `884702484135319409` / `702265252016400947` — uid ≠ mainUid, so this **is a sub-account** |
| Account level | `acctLv 1` (Simple — spot only), `Lv1` fee tier |
| Fees | maker `-0.0008` (8 bps), taker `-0.001` (10 bps); OKX returns these negative as a cost, the worker takes the absolute value |
| Balance | **`totalEq = 0`** — trading, funding and valuation all empty |
| Open orders | 0 |
| `demo` | `false` — these are **live** credentials; only `MODE=observe` prevents trading |

The same key authenticates against both `tr.okx.com` and `www.okx.com` returning the
same uid. This was falsified properly: a bogus `OKX_API_BASE_URL` fails and a bogus
`OKX_SITE` refuses to start, so the override is genuinely honoured and the two hosts
really do resolve to one account. `OKX_SITE=tr` is therefore correct.

### Burst limitation (measured, not theoretical)

The 500-print page is sized for the average tape, and the average is misleading.
On 12 Sep two consecutive BTC-USDT polls **16 seconds apart** lost **1557 and
2426 prints**. The cause was not a stall: a large order swept the book and emitted
~1200 micro-prints (~23 USDT each, against a ~2,800 USDT normal print) in about
20 seconds, overrunning the page between polls. Over that period roughly 40% of
BTC prints were never captured.

Three consequences, all handled rather than hidden:

* The trade poll interval is **5s**, sized for bursts rather than the mean rate.
* A gap is recorded with its **time bounds**, not only its id range.
* `compute_flow` **refuses to produce a reading when a gap overlaps its window**.
  This matters more than sampling noise: the prints lost in a sweep are mostly on
  one side of it, so an imbalance computed over a holed window is wrong in a
  specific direction, not merely noisy.

Polling at 5s reduces but cannot eliminate this. A sufficiently violent sweep will
still overrun the page, and the honest answer is then "no flow signal", not a
number. This is the strongest argument for a real WebSocket feed if the
competition rules permit one alongside ATK.

Two ATK behaviours worth knowing:

* **Partial credentials are fatal.** Key + secret without passphrase makes ATK exit at
  startup with `ConfigError: Partial API credentials detected.` The client therefore
  passes credentials all-or-nothing and falls back to unauthenticated market-only mode.
* **Replies exceed asyncio's default line limit.** A 500-print reply is ~90KB against a
  64KiB default, which tore down the session; the stdio reader now uses a 16MB limit.

## Safety properties

* Risk engine is deterministic and separate from the model. The LLM cannot size, place,
  or cancel anything; write tools are reachable only from the order manager.
* Tool allowlist is enforced in code — module selection alone is not treated as a control
  (`--modules spot` would still expose batch order tools).
* An ATK call timeout is `UNKNOWN`, never "cancelled": write callers must reconcile.
* Missing data is never neutral. Invalid flow rejects a setup; it never reads as
  balanced. Thin books (<20 prints/60s) yield no flow signal rather than a maximally
  confident one.
* Risk budget is a ceiling, not a target: the stop is never widened to spend it, and
  quantity is never rounded up to reach a venue minimum.

## Startup reconciliation

No entry can be opened until the ledger agrees with the venue. The worker runs this
before trading and the gate rejects with `RECONCILE_INCOMPLETE` until it is clean;
the dashboard shows `reconciled` / `UNRECONCILED` in the status strip.

| Situation on restart | Resolution |
|---|---|
| Intent reserved, no order row | Released — the row is written *before* the send, so its absence is our own record, not a guess about the venue |
| Order in flight / `UNKNOWN` | Queried by client order id; the venue's answer decides |
| Venue cannot be reached | Stays unresolved and **keeps trading blocked** — silence is never treated as "it didn't happen" |
| Fills that landed while down | Ingested idempotently (dedup by venue fill id) |
| Entry filled but no position row | Position **rebuilt** from stored fills + the intent's frozen stop, and protection re-attached |
| Ledger shows a position, venue shows no balance | Closed externally (stop or TP filled while down) |
| Open position with no live algo order | Flagged as an incident — but does **not** block, since refusing to run would also refuse to manage it |
| Base currency we cannot account for | Reported, never adopted — adopting it would invent an entry price and an R basis |

The rebuild case is the one worth understanding: a crash between the fill and the
position insert leaves real inventory with no stop and no exit ladder. Nothing is
invented in rebuilding it — the quantity and average price come from actual stored
fills, and the structural stop and policy version from the durable intent row.

## Known gaps

1. **The account is unfunded (`totalEq = 0`).** Authentication works and the real fee
   tier is read from the venue, but no entry can be sized until the competition credit
   is allocated or funds are transferred in. The worker logs `account_unfunded` and the
   risk engine rejects with `NO_EQUITY` rather than sizing against a placeholder.
   Transferring funds is a manual step — `account_transfer` is deliberately not in the
   tool allowlist.
2. **No order path.** `observe` mode records `BUY_INTENT` conditions but never sends an
   order. Intent → reservation → order → fill → reconcile (Gate 2) is not built.
3. **Unverified competition rules**: sub-account, starting credit, permitted pairs, real
   fee tier, and the 19:30 open-position rule still need confirming from the organiser.
4. **Polling, not streaming.** Order flow is reconstructed from polled prints and is not
   a tick feed. During book sweeps prints are provably lost (see *Burst limitation*);
   the flow feature then reports invalid rather than guessing.
5. **`MODE=live` has still never been exercised.** Every test covers `observe` and
   `paper`. The first live order will be the first live order.
6. `AGENTIC_TRADING_HACKATHON_PLAYBOOK.md`, referenced by AGENT.md, does not exist.

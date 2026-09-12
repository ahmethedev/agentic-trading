-- Agentic Trade schema (PostgreSQL 17)
-- Single persistent store: market archive + decision/order/fill ledger.
-- Decision chain: decision_id -> intent_id -> client_order_id -> exchange_order_id -> fill_id

CREATE SCHEMA IF NOT EXISTS at;
SET search_path TO at, public;

-- ---------------------------------------------------------------- sessions --
-- One row per worker process start. Every record is attributable to a run.
CREATE TABLE IF NOT EXISTS runs (
    run_id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    stopped_at      TIMESTAMPTZ,
    mode            TEXT NOT NULL CHECK (mode IN ('observe','paper','live')),
    venue           TEXT NOT NULL DEFAULT 'okx-tr',
    site            TEXT NOT NULL,
    demo            BOOLEAN NOT NULL,
    policy_version  TEXT NOT NULL,
    code_version    TEXT,
    schema_version  INT  NOT NULL DEFAULT 1,
    notes           TEXT
);

-- ----------------------------------------------------------- market archive --
CREATE TABLE IF NOT EXISTS candles (
    venue        TEXT        NOT NULL,
    inst_id      TEXT        NOT NULL,
    bar          TEXT        NOT NULL,           -- '1m','5m','15m'
    open_time    TIMESTAMPTZ NOT NULL,           -- exchange candle open
    open         NUMERIC(38,18) NOT NULL,
    high         NUMERIC(38,18) NOT NULL,
    low          NUMERIC(38,18) NOT NULL,
    close        NUMERIC(38,18) NOT NULL,
    vol_base     NUMERIC(38,18) NOT NULL,
    vol_quote    NUMERIC(38,18) NOT NULL,
    confirm      BOOLEAN     NOT NULL,           -- OKX `confirm` field: candle closed
    received_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_id       BIGINT      REFERENCES runs(run_id),
    PRIMARY KEY (venue, inst_id, bar, open_time)
);
CREATE INDEX IF NOT EXISTS candles_lookup
    ON candles (inst_id, bar, open_time DESC) WHERE confirm;

-- Public taker-side trade prints. Source for flow_imbalance.
-- trade_id is the dedup + gap-detection key (verified contiguous on OKX TR).
CREATE TABLE IF NOT EXISTS market_trades (
    venue        TEXT        NOT NULL,
    inst_id      TEXT        NOT NULL,
    trade_id     BIGINT      NOT NULL,
    ts           TIMESTAMPTZ NOT NULL,           -- exchange timestamp
    px           NUMERIC(38,18) NOT NULL,
    sz           NUMERIC(38,18) NOT NULL,
    side         TEXT        NOT NULL CHECK (side IN ('buy','sell')),  -- taker side
    received_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_id       BIGINT      REFERENCES runs(run_id),
    PRIMARY KEY (venue, inst_id, trade_id)
);
CREATE INDEX IF NOT EXISTS market_trades_window ON market_trades (inst_id, ts DESC);

CREATE TABLE IF NOT EXISTS book_snapshots (
    venue        TEXT        NOT NULL,
    inst_id      TEXT        NOT NULL,
    ts           TIMESTAMPTZ NOT NULL,
    bids         JSONB       NOT NULL,
    asks         JSONB       NOT NULL,
    depth        INT         NOT NULL,
    received_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_id       BIGINT      REFERENCES runs(run_id),
    PRIMARY KEY (venue, inst_id, ts)
);

-- Explicit record of what we could NOT observe. Absence of data must never be
-- silently read as "no activity".
CREATE TABLE IF NOT EXISTS data_gaps (
    gap_id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    venue        TEXT        NOT NULL,
    inst_id      TEXT        NOT NULL,
    stream       TEXT        NOT NULL,           -- 'trades' | 'candles' | 'book'
    detected_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    gap_from     TIMESTAMPTZ,
    gap_to       TIMESTAMPTZ,
    first_missing_id BIGINT,
    last_missing_id  BIGINT,
    missing_count    BIGINT,
    reason       TEXT NOT NULL,
    run_id       BIGINT REFERENCES runs(run_id)
);
CREATE INDEX IF NOT EXISTS data_gaps_recent ON data_gaps (inst_id, detected_at DESC);

-- Instrument specs (lot size, min size, tick). Fetched from the venue, never
-- hardcoded -- quantity rounding depends on these.
CREATE TABLE IF NOT EXISTS instruments (
    venue        TEXT NOT NULL,
    inst_id      TEXT NOT NULL,
    base_ccy     TEXT NOT NULL,
    quote_ccy    TEXT NOT NULL,
    tick_sz      NUMERIC(38,18) NOT NULL,
    lot_sz       NUMERIC(38,18) NOT NULL,
    min_sz       NUMERIC(38,18) NOT NULL,
    state        TEXT NOT NULL,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (venue, inst_id)
);

-- --------------------------------------------------------------- decisions --
-- Feature snapshot + agent output for every evaluation, including WAIT. The
-- reason a trade did NOT happen is as much a deliverable as a trade.
CREATE TABLE IF NOT EXISTS decisions (
    decision_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id          BIGINT NOT NULL REFERENCES runs(run_id),
    inst_id         TEXT   NOT NULL,
    decided_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    candle_open_time TIMESTAMPTZ,                -- the closed candle evaluated
    episode_id      TEXT,                        -- dedups one setup seen over many bars
    action          TEXT NOT NULL CHECK (action IN ('BUY_INTENT','WAIT')),
    setup_id        TEXT,
    reason_codes    TEXT[] NOT NULL DEFAULT '{}',
    stage_reached   TEXT   NOT NULL,             -- opportunity-funnel stage
    features        JSONB  NOT NULL,             -- exact inputs behind the call
    policy_version  TEXT   NOT NULL,
    model_id        TEXT,
    data_quality    JSONB  NOT NULL,             -- staleness, flow coverage, gaps
    valid_until     TIMESTAMPTZ,
    CONSTRAINT decisions_intent_needs_setup
        CHECK (action <> 'BUY_INTENT' OR setup_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS decisions_recent ON decisions (inst_id, decided_at DESC);
CREATE INDEX IF NOT EXISTS decisions_episode ON decisions (episode_id) WHERE episode_id IS NOT NULL;

-- --------------------------------------------------- intents & reservations --
-- A durable intent + risk reservation is written BEFORE any order is sent, so a
-- crash between send and ack is always recoverable.
CREATE TABLE IF NOT EXISTS intents (
    intent_id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    decision_id      BIGINT NOT NULL REFERENCES decisions(decision_id),
    run_id           BIGINT NOT NULL REFERENCES runs(run_id),
    inst_id          TEXT   NOT NULL,
    side             TEXT   NOT NULL CHECK (side IN ('buy','sell')),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    status           TEXT   NOT NULL CHECK (status IN
                        ('RESERVED','SENT','UNKNOWN','ACKED','PARTIAL','FILLED',
                         'CANCELLED','REJECTED','EXPIRED','RECONCILED')),
    -- frozen risk basis: never recomputed after the entry resolves
    equity_at_decision   NUMERIC(38,18) NOT NULL,
    risk_fraction        NUMERIC(10,8)  NOT NULL,
    risk_budget          NUMERIC(38,18) NOT NULL,
    entry_reference      NUMERIC(38,18) NOT NULL,
    structural_stop      NUMERIC(38,18) NOT NULL,
    price_r_distance     NUMERIC(38,18) NOT NULL CHECK (price_r_distance > 0),
    qty_requested        NUMERIC(38,18) NOT NULL,
    est_cost_per_unit    NUMERIC(38,18) NOT NULL DEFAULT 0,
    policy_version       TEXT NOT NULL,
    expires_at           TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS intents_open ON intents (status) WHERE status NOT IN
    ('FILLED','CANCELLED','REJECTED','EXPIRED','RECONCILED');

-- ------------------------------------------------------------------ orders --
CREATE TABLE IF NOT EXISTS orders (
    client_order_id   TEXT PRIMARY KEY,          -- our idempotency key
    intent_id         BIGINT NOT NULL REFERENCES intents(intent_id),
    run_id            BIGINT NOT NULL REFERENCES runs(run_id),
    venue             TEXT NOT NULL,
    inst_id           TEXT NOT NULL,
    exchange_order_id TEXT,
    algo_id           TEXT,                      -- for TP/SL (algo) orders
    purpose           TEXT NOT NULL CHECK (purpose IN
                        ('ENTRY','STOP','TP1','TP2','RUNNER_EXIT','FLATTEN')),
    side              TEXT NOT NULL CHECK (side IN ('buy','sell')),
    ord_type          TEXT NOT NULL,
    px_limit          NUMERIC(38,18),
    qty_requested     NUMERIC(38,18) NOT NULL,
    qty_filled        NUMERIC(38,18) NOT NULL DEFAULT 0,
    avg_px            NUMERIC(38,18),
    status            TEXT NOT NULL,
    sent_at           TIMESTAMPTZ,
    acked_at          TIMESTAMPTZ,
    terminal_at       TIMESTAMPTZ,
    last_reconciled_at TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (venue, exchange_order_id)
);
CREATE INDEX IF NOT EXISTS orders_live ON orders (status)
    WHERE terminal_at IS NULL;

-- Append-only order lifecycle log. Late acks must never rewind a terminal state,
-- so history is kept separately from the current view above.
CREATE TABLE IF NOT EXISTS order_events (
    event_id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    client_order_id TEXT NOT NULL REFERENCES orders(client_order_id),
    event_type      TEXT NOT NULL,
    payload         JSONB NOT NULL,
    venue_ts        TIMESTAMPTZ,
    received_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS order_events_by_order ON order_events (client_order_id, event_id);

-- ------------------------------------------------------------------- fills --
-- Unique on the venue fill id: the same fill can arrive from polling and from
-- reconciliation, and must be counted exactly once.
CREATE TABLE IF NOT EXISTS fills (
    venue            TEXT NOT NULL,
    fill_id          TEXT NOT NULL,
    client_order_id  TEXT REFERENCES orders(client_order_id),
    exchange_order_id TEXT,
    inst_id          TEXT NOT NULL,
    side             TEXT NOT NULL CHECK (side IN ('buy','sell')),
    px               NUMERIC(38,18) NOT NULL,
    qty              NUMERIC(38,18) NOT NULL,
    fee              NUMERIC(38,18) NOT NULL,
    fee_ccy          TEXT NOT NULL,
    liquidity        TEXT,                       -- maker / taker
    ts               TIMESTAMPTZ NOT NULL,
    received_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_id           BIGINT REFERENCES runs(run_id),
    PRIMARY KEY (venue, fill_id)
);
CREATE INDEX IF NOT EXISTS fills_by_order ON fills (client_order_id);

-- ---------------------------------------------------------------- positions --
CREATE TABLE IF NOT EXISTS positions (
    position_id      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id           BIGINT NOT NULL REFERENCES runs(run_id),
    intent_id        BIGINT REFERENCES intents(intent_id),
    inst_id          TEXT NOT NULL,
    opened_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at        TIMESTAMPTZ,
    status           TEXT NOT NULL CHECK (status IN ('OPEN','CLOSING','CLOSED')),
    -- frozen at entry resolution; the R denominator never shrinks afterwards
    initial_qty          NUMERIC(38,18) NOT NULL,
    avg_entry_px         NUMERIC(38,18) NOT NULL,
    initial_stop_px      NUMERIC(38,18) NOT NULL,
    frozen_risk_amount   NUMERIC(38,18) NOT NULL,
    price_r_distance     NUMERIC(38,18) NOT NULL,
    qty_open             NUMERIC(38,18) NOT NULL,
    current_stop_px      NUMERIC(38,18),
    tp1_done             BOOLEAN NOT NULL DEFAULT FALSE,
    tp2_done             BOOLEAN NOT NULL DEFAULT FALSE,
    breakeven_moved      BOOLEAN NOT NULL DEFAULT FALSE,
    realized_pnl         NUMERIC(38,18) NOT NULL DEFAULT 0,
    fees_paid            NUMERIC(38,18) NOT NULL DEFAULT 0,
    -- Entry fees, kept separately so they can be amortised pro-rata into
    -- realised PnL as inventory is sold (exit fees alone understate cost).
    entry_fees           NUMERIC(38,18) NOT NULL DEFAULT 0,
    policy_version       TEXT NOT NULL,
    CONSTRAINT positions_qty_open_sane CHECK (qty_open >= 0 AND qty_open <= initial_qty)
);
CREATE INDEX IF NOT EXISTS positions_open ON positions (status) WHERE status <> 'CLOSED';

CREATE TABLE IF NOT EXISTS equity_snapshots (
    snapshot_id  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id       BIGINT NOT NULL REFERENCES runs(run_id),
    ts           TIMESTAMPTZ NOT NULL DEFAULT now(),
    equity_quote NUMERIC(38,18) NOT NULL,
    realized_pnl NUMERIC(38,18) NOT NULL DEFAULT 0,
    unrealized_pnl NUMERIC(38,18) NOT NULL DEFAULT 0,
    fees_total   NUMERIC(38,18) NOT NULL DEFAULT 0,
    source       TEXT NOT NULL                   -- 'venue' | 'derived'
);
CREATE INDEX IF NOT EXISTS equity_ts ON equity_snapshots (run_id, ts DESC);

-- ------------------------------------------------------------------- ops ----
CREATE TABLE IF NOT EXISTS ops_events (
    ops_id      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id      BIGINT REFERENCES runs(run_id),
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    severity    TEXT NOT NULL CHECK (severity IN ('info','warn','error')),
    kind        TEXT NOT NULL,                   -- reconcile / timeout / stale / atk_restart
    inst_id     TEXT,
    detail      JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ops_recent ON ops_events (ts DESC);

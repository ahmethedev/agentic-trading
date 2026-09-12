import React, { useCallback, useEffect, useState } from 'react'
import Chart from './Chart.jsx'
import {
  getCandles, getDecisions, getFlow, getFunnel, getInstruments, getPositions,
  getStatus,
} from './api.js'

const REFRESH_MS = 5000

/* Codes that mean "this check passed / is informational", not a rejection. */
const PASS_CODES = new Set(['RECLAIM_CONFIRMED'])

const fmt = (v, d = 2) =>
  v === null || v === undefined ? '—' : Number(v).toFixed(d)

/* Quantities arrive as full-precision decimals (e.g. "0.009945000000000000",
   "0E-18"). Trim to something readable without inventing or hiding precision. */
const qty = (v) => {
  if (v === null || v === undefined) return '—'
  const n = Number(v)
  if (!Number.isFinite(n)) return String(v)
  if (n === 0) return '0'
  const d = n >= 1 ? 4 : 8
  return n.toFixed(d).replace(/\.?0+$/, '')
}

/* Prices arrive as full-precision decimal strings; show a readable number of
   significant digits without implying more precision than the tick size. */
const price = (v) => {
  if (v === null || v === undefined) return '—'
  const n = Number(v)
  if (!Number.isFinite(n)) return String(v)
  const d = n >= 1000 ? 1 : n >= 1 ? 3 : 6
  return n.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: d })
}

const ago = (iso) => {
  if (!iso) return '—'
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return `${Math.round(s)}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  return `${Math.floor(s / 3600)}h ago`
}

function StatusStrip({ status }) {
  if (!status) return <div className="strip"><span className="pill">connecting…</span></div>
  const stale = status.data_freshness.filter((f) => f.age_s > 45)
  const running = status.run_started_at && !status.run_stopped_at
  return (
    <div className="strip">
      <h1>Agentic Trade</h1>
      <span className={`pill ${status.mode === 'live' ? 'bad' : 'warn'}`}>
        {status.mode.toUpperCase()}
      </span>
      <span className="pill">{status.site.toUpperCase()}{status.demo ? ' · DEMO' : ''}</span>
      <span className={`pill ${status.authenticated ? 'ok' : 'bad'}`}>
        {status.authenticated ? 'AUTHENTICATED' : `NO AUTH: ${status.missing_credentials.join(', ')}`}
      </span>
      <span className="pill">{status.policy_version ?? 'no policy'}</span>
      <span className="pill">risk {(+status.risk_fraction * 100).toFixed(1)}% · cap {(+status.risk_fraction_max * 100).toFixed(1)}%</span>
      <span className="spacer" />
      <span className={`pill ${stale.length ? 'bad' : 'ok'}`}>
        {stale.length ? `${stale.length} STALE FEED` : 'DATA FRESH'}
      </span>
      <span className={`pill ${status.gaps_last_hour ? 'warn' : 'ok'}`}>
        gaps 1h: {status.gaps_last_hour}
      </span>
      <span className={`pill ${running ? 'ok' : 'bad'}`}>
        worker {running ? 'running' : 'stopped'}
      </span>
      {/* Until reconciliation is clean the gate refuses every entry. */}
      {status.reconcile && (
        <span className={`pill ${status.reconcile.clean ? 'ok' : 'bad'}`}>
          {status.reconcile.clean
            ? 'reconciled'
            : `UNRECONCILED (${(status.reconcile.unresolved ?? []).length})`}
        </span>
      )}
      {status.reconcile?.unprotected_positions?.length > 0 && (
        <span className="pill bad">
          {status.reconcile.unprotected_positions.length} UNPROTECTED
        </span>
      )}
    </div>
  )
}

function DecisionCard({ d }) {
  const f = d.features ?? {}
  const s = f.setup ?? {}
  const buy = d.action === 'BUY_INTENT'
  return (
    <div className="card">
      <div className="card-head">
        <span className="sym">{d.inst_id}</span>
        <span className={`badge ${buy ? 'buy' : 'wait'}`}>{d.action}</span>
        <span className="pill">{d.stage_reached}</span>
        <span className="time">{ago(d.decided_at)}</span>
      </div>
      <div className="kv">
        <div><div className="k">close</div><div className="v">{price(f.close)}</div></div>
        <div><div className="k">rvol</div><div className="v">{fmt(f.rvol)}</div></div>
        <div>
          <div className="k">flow imb</div>
          <div className="v">{f.flow_valid ? fmt(f.flow_imbalance, 3) : 'invalid'}</div>
        </div>
        <div><div className="k">above ma</div><div className="v">{String(f.above_ma ?? '—')}</div></div>
        <div><div className="k">slope/atr</div><div className="v">{fmt(f.trend_slope_atr, 4)}</div></div>
        <div><div className="k">atr</div><div className="v">{price(f.atr)}</div></div>
      </div>
      {s.level && (
        <div className="kv">
          <div><div className="k">level</div><div className="v">{price(s.level)}</div></div>
          <div><div className="k">pullback low</div><div className="v">{price(s.pullback_low)}</div></div>
          <div><div className="k">depth atr</div><div className="v">{fmt(s.pullback_depth_atr, 2)}</div></div>
          <div><div className="k">ext atr</div><div className="v">{fmt(s.extension_atr, 2)}</div></div>
        </div>
      )}
      {f.sizing && Object.keys(f.sizing).length > 0 && (
        <div className="kv">
          <div><div className="k">qty</div><div className="v">{f.sizing.quantity ?? f.sizing.rejected ?? '—'}</div></div>
          <div><div className="k">risk budget</div><div className="v">{price(f.sizing.risk_budget)}</div></div>
          <div><div className="k">risk at stop</div><div className="v">{price(f.sizing.risk_at_stop)}</div></div>
          <div><div className="k">capped by</div><div className="v">{(f.sizing.capped_by ?? []).join(',') || '—'}</div></div>
        </div>
      )}
      <div className="codes">
        {d.reason_codes.map((c, i) => (
          <span key={i} className={`code ${PASS_CODES.has(c) ? 'pass' : ''}`}>{c}</span>
        ))}
      </div>
    </div>
  )
}

function Positions({ data }) {
  if (!data) return null
  const { positions, orders } = data
  return (
    <div className="panel">
      <h2>Positions</h2>
      {positions.length === 0 && <div className="empty">no positions yet</div>}
      {positions.map((p) => (
        <div className="card" key={p.position_id}>
          <div className="card-head">
            <span className="sym">{p.inst_id}</span>
            <span className={`badge ${p.status === 'OPEN' ? 'buy' : 'wait'}`}>
              {p.status}
            </span>
            {/* An open position without venue-side protection is an incident. */}
            {p.status !== 'CLOSED' && (
              <span className={`pill ${p.protected ? 'ok' : 'bad'}`}>
                {p.protected ? 'protected' : 'UNPROTECTED'}
              </span>
            )}
            <span className="time">{ago(p.opened_at)}</span>
          </div>
          <div className="kv">
            <div><div className="k">entry</div><div className="v">{price(p.avg_entry_px)}</div></div>
            <div><div className="k">stop</div><div className="v">{price(p.current_stop_px ?? p.initial_stop_px)}</div></div>
            <div><div className="k">qty open</div><div className="v">{qty(p.qty_open)}</div></div>
            <div><div className="k">realized R</div><div className="v">{p.realized_r ?? '—'}</div></div>
            <div><div className="k">realized pnl</div><div className="v">{price(p.realized_pnl)}</div></div>
            <div><div className="k">fees</div><div className="v">{price(p.fees_paid)}</div></div>
          </div>
          <div className="codes">
            <span className={`code ${p.breakeven_moved ? 'pass' : ''}`}>
              +1R breakeven {p.breakeven_moved ? 'done' : 'pending'}
            </span>
            <span className={`code ${p.tp1_done ? 'pass' : ''}`}>
              +2R tp1 {p.tp1_done ? 'done' : 'pending'}
            </span>
            <span className={`code ${p.tp2_done ? 'pass' : ''}`}>
              +2.5R tp2 {p.tp2_done ? 'done' : 'pending'}
            </span>
          </div>
        </div>
      ))}
      {orders.length > 0 && (
        <>
          <h2 style={{ marginTop: 14 }}>Orders</h2>
          <table>
            <thead>
              <tr><th>Purpose</th><th>Type</th><th>Status</th><th>Filled</th><th>Avg</th></tr>
            </thead>
            <tbody>
              {orders.slice(0, 10).map((o) => (
                <tr key={o.client_order_id}>
                  <td>{o.purpose}</td>
                  <td className="muted">{o.ord_type}</td>
                  <td className={o.status === 'REJECTED' || o.status === 'UNKNOWN' ? 'code' : ''}>
                    {o.status}
                  </td>
                  <td>{qty(o.qty_filled)}/{qty(o.qty_requested)}</td>
                  <td>{o.avg_px ? price(o.avg_px) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  )
}

function Funnel({ funnel }) {
  if (!funnel) return null
  const max = Math.max(1, ...funnel.stages.map((s) => s.evaluations))
  return (
    <div className="panel">
      <h2>Opportunity funnel · {funnel.window_hours}h</h2>
      {funnel.stages.length === 0 && <div className="empty">no evaluations yet</div>}
      {funnel.stages.map((s) => (
        <div className="funnel-row" key={s.stage}>
          <span className="funnel-label">{s.stage}</span>
          <div className="funnel-bar" style={{ width: `${(s.evaluations / max) * 55}%` }} />
          <span className="funnel-n">{s.evaluations}</span>
          {s.episodes > 0 && <span className="muted">· {s.episodes} ep</span>}
        </div>
      ))}
      <div className="note">
        Bars count evaluations; “ep” counts distinct setup episodes, so one setup
        seen across many bars is not inflated into many opportunities.
        {funnel.seconds_since_last_confirmed !== null
          ? ` Last confirmed candidate ${Math.round(funnel.seconds_since_last_confirmed / 60)}m ago.`
          : ' No confirmed candidate yet in this window.'}
      </div>
    </div>
  )
}

function ReasonCodes({ funnel }) {
  if (!funnel?.reason_codes?.length) return null
  return (
    <div className="panel">
      <h2>Why not / why yes</h2>
      <table>
        <thead><tr><th>Reason code</th><th style={{ textAlign: 'right' }}>Count</th></tr></thead>
        <tbody>
          {funnel.reason_codes.map((r) => (
            <tr key={r.code}>
              <td>{r.code}</td>
              <td style={{ textAlign: 'right' }}>{r.count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function DataHealth({ status }) {
  if (!status) return null
  return (
    <div className="panel">
      <h2>Data health</h2>
      <table>
        <thead>
          <tr><th>Instrument</th><th>Last print</th><th>Trades/60s</th></tr>
        </thead>
        <tbody>
          {status.data_freshness.map((f) => (
            <tr key={f.inst_id}>
              <td>{f.inst_id}</td>
              <td className={f.age_s > 45 ? 'code' : ''}>{fmt(f.age_s, 0)}s</td>
              <td>{f.trades_60s}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {status.ops_events.length > 0 && (
        <>
          <h2 style={{ marginTop: 14 }}>Ops events</h2>
          <table>
            <tbody>
              {status.ops_events.slice(0, 6).map((e, i) => (
                <tr key={i}>
                  <td className="muted">{ago(e.ts)}</td>
                  <td>{e.kind}</td>
                  <td className={e.severity === 'error' ? 'code' : 'muted'}>{e.severity}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  )
}

export default function App() {
  const [status, setStatus] = useState(null)
  const [decisions, setDecisions] = useState([])
  const [funnel, setFunnel] = useState(null)
  const [instruments, setInstruments] = useState([])
  const [selected, setSelected] = useState(null)
  const [candles, setCandles] = useState([])
  const [positions, setPositions] = useState(null)
  const [err, setErr] = useState(null)

  useEffect(() => {
    getInstruments().then((xs) => {
      setInstruments(xs)
      if (xs.length && !selected) setSelected(xs[0].inst_id)
    }).catch((e) => setErr(e.message))
  }, [])

  const refresh = useCallback(async () => {
    try {
      const [st, de, fu, po] = await Promise.all([
        getStatus(), getDecisions(null, 30), getFunnel(6), getPositions(),
      ])
      setStatus(st); setDecisions(de); setFunnel(fu); setPositions(po); setErr(null)
      if (selected) setCandles(await getCandles(selected, '5m'))
    } catch (e) { setErr(e.message) }
  }, [selected])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, REFRESH_MS)
    return () => clearInterval(id)
  }, [refresh])

  const latestForSelected = decisions.find((d) => d.inst_id === selected)
  const setup = latestForSelected?.features?.setup ?? {}
  const markers = {
    level: setup.level ? Number(setup.level) : null,
    stop: setup.pullback_low ? Number(setup.pullback_low) : null,
  }

  return (
    <div className="app">
      <StatusStrip status={status} />
      {err && <div className="panel" style={{ marginBottom: 14 }}>
        <span className="code">API error: {err}</span>
      </div>}

      <div className="tabs">
        {instruments.map((i) => (
          <button
            key={i.inst_id}
            className={`tab ${selected === i.inst_id ? 'active' : ''}`}
            onClick={() => setSelected(i.inst_id)}
          >{i.inst_id}</button>
        ))}
      </div>

      <div className="grid">
        <div className="stack">
          <div className="panel">
            <h2>{selected ?? '—'} · 5m</h2>
            <Chart candles={candles} markers={markers} />
            <div className="note">
              Dashed blue = the level defined by earlier closed candles; dashed red =
              the structural stop (pullback low). Both come from the stored decision
              record, not recomputed here.
            </div>
          </div>
          <div className="panel">
            <h2>Decision cards</h2>
            {decisions.length === 0 && <div className="empty">no decisions recorded yet</div>}
            {decisions.slice(0, 12).map((d) => <DecisionCard key={d.decision_id} d={d} />)}
          </div>
        </div>

        <div className="stack">
          <Positions data={positions} />
          <Funnel funnel={funnel} />
          <DataHealth status={status} />
          <ReasonCodes funnel={funnel} />
        </div>
      </div>
    </div>
  )
}

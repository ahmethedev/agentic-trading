import React, { useEffect, useRef, useState } from "react";
import Chart from "./Chart.jsx";
import {
  askQuant,
  askQuantStream,
  createDraft,
  getBacktest,
  getCandles,
  getExperiment,
  getExperiments,
  getMarket,
  getSession,
  getStrategy,
  getWorkspace,
  login,
  logout,
  startExperiment,
  stopExperimentRun,
} from "./api.js";

const fmt = (v, digits = 2) =>
  v === null || v === undefined || !Number.isFinite(+v)
    ? "—"
    : (+v).toLocaleString("tr-TR", { maximumFractionDigits: digits });
const stamp = (v) =>
  v
    ? new Date(v).toLocaleString("tr-TR", {
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })
    : "Henüz yok";
const modeLabel = (run) =>
  !run
    ? "Piyasa keşfi"
    : run.demo
      ? `${run.mode.toUpperCase()} · OKX demo hesabı`
      : run.mode === "live"
        ? "LIVE · Gerçek hesap"
        : "OBSERVE · Emir göndermez";
const views = [
  { id: "overview", name: "Genel bakış", icon: "overview" },
  { id: "strategies", name: "Stratejiler", icon: "strategy" },
  { id: "backtest", name: "Backtest", icon: "backtest" },
  { id: "experiments", name: "Deneyler", icon: "experiment" },
];
const toolLabels = {
  get_market_overview: "Piyasa görünümü",
  get_strategy: "Strateji sürümü",
  get_decision_funnel: "Karar kayıtları",
  get_risk_summary: "Risk ve maliyet",
  get_recent_fills: "Gerçekleşen işlemler",
  get_run_status: "Çalışma durumu",
};
const prompts = [
  "Piyasanın fotoğrafını çıkar",
  "Neden işlem açmadık?",
  "Stratejim nasıl çalışıyor?",
  "Hangi paritelerde kurulum oluşuyor?",
];

function Icon({ name, ...props }) {
  const paths = {
    overview: (
      <>
        <rect x="3" y="3" width="7" height="7" rx="1.5" />
        <rect x="14" y="3" width="7" height="7" rx="1.5" />
        <rect x="3" y="14" width="7" height="7" rx="1.5" />
        <rect x="14" y="14" width="7" height="7" rx="1.5" />
      </>
    ),
    strategy: (
      <>
        <path d="M5 3v18M3 7h4M3 16h4M12 3v18M10 12h4M19 3v18M17 8h4M17 17h4" />
      </>
    ),
    experiment: (
      <>
        <path d="M9 3h6M10 3v7l-6 9q-1 2 2 2h12q3 0 2-2l-6-9V3M7 15h10" />
      </>
    ),
    backtest: (
      <>
        <path d="M4 19V5M4 19h16" />
        <path d="m7 15 4-4 3 2 5-6" />
      </>
    ),
    link: (
      <>
        <path
          d="m9 15 6-6M8 16l-1 1a4 4 0 0 1-6-6l4-4a4 4 0 0 1 6 0M16 8l1-1a4 4 0 0 1 6 6l-4 4a4 4 0 0 1-6 0"
          transform="translate(0 -1)"
        />
      </>
    ),
    chat: (
      <>
        <path d="M4 4h16v12H9l-5 4V4Z" />
        <path d="M8 8h8M8 12h5" />
      </>
    ),
    arrow: (
      <>
        <path d="M5 12h14m-6-6 6 6-6 6" />
      </>
    ),
    check: <path d="m5 12 4 4L19 6" />,
  };
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      {paths[name] || paths.overview}
    </svg>
  );
}
function Empty({ title, children }) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}
function Metric({ label, value, unit, detail }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>
        {value}
        <small>{unit}</small>
      </strong>
      <p>{detail}</p>
    </div>
  );
}
function StrategyCard({ strategy, run, onAsk, expanded = false }) {
  if (!strategy)
    return (
      <Empty title="Kurallar yükleniyor">Strateji servisi bekleniyor.</Empty>
    );
  return (
    <section className="panel strategy-card">
      <div className="section-head">
        <div>
          <span className="eyebrow">Benim stratejim</span>
          <h2>{strategy.name}</h2>
        </div>
        <span className="badge">
          {run?.health === "recent_decisions"
            ? "İzleniyor"
            : "Referans kurallar"}
        </span>
      </div>
      <div className="rule-pills">
        <span>15m bağlam</span>
        <span>5m kurulum</span>
        <span>Spot · Long</span>
        <span>{strategy.version}</span>
      </div>
      <p>
        Geri çekilmenin ardından seviyeyi geri kazanan fiyatı, hacim ve alıcı
        baskısıyla doğrular.
      </p>
      {expanded && (
        <>
          <ol className="rules">
            {strategy.rules.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ol>
          <p>{strategy.risk}</p>
          <div className="callout">
            <strong>Bugün çalışan çıkış</strong>
            <p>{strategy.execution}</p>
            <p>{strategy.exit_reference}</p>
          </div>
          <p className="fine">{strategy.source}</p>
        </>
      )}
      <button
        className="text-button"
        onClick={() => onAsk("Stratejim nasıl çalışıyor?")}
      >
        Kuralları açıkla <Icon name="arrow" />
      </button>
    </section>
  );
}
function DecisionList({ data }) {
  if (!data?.length)
    return (
      <Empty title="Henüz karar yok">
        Yeni değerlendirmeler kaydedildiğinde burada görünecek.
      </Empty>
    );
  return (
    <div className="decision-list">
      {data.slice(0, 4).map((d) => (
        <details key={d.decision_id} className="decision">
          <summary>
            <span className="decision-symbol">{d.inst_id.split("-")[0]}</span>
            <span className="decision-copy">
              <strong>{d.reasons?.[0] || d.stage_reached}</strong>
              <small>
                #{d.decision_id} · {stamp(d.decided_at)}
              </small>
            </span>
            <span className="badge">
              {d.action === "BUY_INTENT" ? "Giriş niyeti" : "Bekliyor"}
            </span>
          </summary>
          <div className="decision-detail">
            <p>{d.reasons.join(" · ")}</p>
            <p>
              Göreli hacim {fmt(d.features?.rvol)} · Akış{" "}
              {fmt(d.features?.flow_imbalance, 3)}
            </p>
            <p className="fine">
              Run #{d.run_id} · Mum {stamp(d.candle_open_time)} ·{" "}
              {d.stage_reached}
            </p>
          </div>
        </details>
      ))}
    </div>
  );
}
function Chat({ selected, onNavigate, opened, onClose, assistant }) {
  const [draft, setDraft] = useState(""),
    [messages, setMessages] = useState([]),
    [busy, setBusy] = useState(false);
  const [stage, setStage] = useState(null);
  const conversation = useRef(null);
  const [newReply, setNewReply] = useState(false);
  const [compact, setCompact] = useState(window.innerWidth < 1200);
  useEffect(() => {
    const media = window.matchMedia("(max-width:1199px)");
    const update = () => setCompact(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  const scroller = useRef(null),
    nearBottom = useRef(true),
    input = useRef(null),
    inFlight = useRef(false);
  const scroll = () => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight });
    setNewReply(false);
  };
  useEffect(() => {
    const handler = (e) => send(e.detail);
    window.addEventListener("quant-ask", handler);
    return () => window.removeEventListener("quant-ask", handler);
  }, [selected, busy]);
  useEffect(() => {
    if (opened) input.current?.focus();
  }, [opened]);
  useEffect(() => {
    if (nearBottom.current) scroll();
    else setNewReply(true);
  }, [messages, busy]);
  // The answer is written into the last assistant message as it arrives, so
  // the reply appears progressively instead of after a silent wait.
  const patchLast = (fields) =>
    setMessages((m) =>
      m.map((msg, i) =>
        i === m.length - 1 && msg.role === "assistant"
          ? { ...msg, ...(typeof fields === "function" ? fields(msg) : fields) }
          : msg,
      ),
    );

  async function send(text) {
    if (inFlight.current || !text.trim()) return;
    inFlight.current = true;
    setBusy(true);
    setStage(null);
    setDraft("");
    const question = {
      message: text,
      inst_id: selected || null,
      conversation_id: conversation.current,
    };
    setMessages((m) => [
      ...m,
      {
        role: "user",
        text,
        context: /piyasa|pariteler/i.test(text)
          ? "İzlenen pariteler"
          : selected || "İzlenen pariteler",
      },
      { role: "assistant", text: "", streaming: true, stages: [] },
    ]);
    try {
      let answer;
      try {
        answer = await askQuantStream(question, (event) => {
          if (event.type === "text")
            patchLast((msg) => ({ text: msg.text + event.delta }));
          else if (event.type === "text_reset") patchLast({ text: "" });
          else if (event.type === "tool" && event.phase === "start") {
            setStage(event.stage);
            patchLast((msg) => ({ stages: [...msg.stages, event.stage] }));
          } else if (event.type === "tool" && event.phase === "end")
            setStage(null);
        });
      } catch (streamError) {
        // A proxy or browser that will not stream must not cost the answer.
        if (streamError.message.includes("(4")) throw streamError;
        patchLast({ text: "", stages: [] });
        answer = await askQuant(text, selected || null, conversation.current);
      }
      conversation.current = answer.conversation_id || conversation.current;
      patchLast({ ...answer, streaming: false });
    } catch (error) {
      setMessages((m) => [
        ...m.filter((msg, i) => !(i === m.length - 1 && msg.streaming)),
        { role: "error", text: error.message },
      ]);
    } finally {
      setStage(null);
      inFlight.current = false;
      setBusy(false);
    }
  }
  return (
    <aside
      className={`chat-panel ${opened ? "is-open" : ""}`}
      aria-label="Ask My Quant"
      role={compact && opened ? "dialog" : undefined}
      aria-modal={compact && opened ? true : undefined}
      onKeyDown={(e) => {
        if (e.key === "Escape") onClose();
        if (e.key === "Tab" && compact && opened) {
          const items = [
            ...e.currentTarget.querySelectorAll(
              "button:not(:disabled),textarea,summary",
            ),
          ].filter((el) => el.getClientRects().length);
          const first = items[0],
            last = items.at(-1);
          if (e.shiftKey && document.activeElement === first) {
            e.preventDefault();
            last?.focus();
          } else if (!e.shiftKey && document.activeElement === last) {
            e.preventDefault();
            first?.focus();
          }
        }
      }}
    >
      <div className="chat-heading">
        <div className="quant-avatar">
          <Icon name="chat" />
        </div>
        <div>
          <h2>Ask My Quant</h2>
          <span>Kayıtlarla düşün.</span>
        </div>
        <button
          className="chat-close"
          onClick={onClose}
          aria-label="Sohbeti kapat"
        >
          ×
        </button>
      </div>
      <div
        className="chat-scroll"
        ref={scroller}
        onScroll={() => {
          const el = scroller.current;
          nearBottom.current =
            el.scrollHeight - el.scrollTop - el.clientHeight < 70;
        }}
      >
        <div className="welcome">
          <span className="eyebrow">Piyasadan kanıta</span>
          <h3>Birlikte neyi inceleyelim?</h3>
          <p>
            Stratejinin ne gördüğünü ve neden beklediğini gerçek kayıtlardan
            incele.
          </p>
        </div>
        <div className="prompts">
          {prompts.map((p) => (
            <button key={p} disabled={busy} onClick={() => send(p)}>
              {p}
              <Icon name="arrow" />
            </button>
          ))}
        </div>
        <p className="fine reader-note">
          {assistant?.enabled
            ? `${assistant.label} · uygulama araçlarıyla kendi kayıtlarını okur. Konuşma sunucu oturumunda tutulur, yeniden başlatınca silinir.`
            : "İlk sürüm: sınırlı sorgu asistanı. LLM bağlı değil; konuşma bu sayfa oturumunda tutulur."}
        </p>
        <div aria-live="polite" aria-relevant="additions">
          {messages.map((m, i) => (
            <article key={i} className={`message ${m.role}`}>
              <span className="message-author">
                {m.role === "user"
                  ? `Siz · ${m.context}`
                  : m.role === "error"
                    ? "Sorgu tamamlanamadı"
                    : "My Quant"}
              </span>
              <p>{m.text}</p>
              {m.streaming && m.stages?.length > 0 && (
                <ul className="stages">
                  {m.stages.map((s, j) => (
                    <li key={j}>{s}…</li>
                  ))}
                </ul>
              )}
              {m.fallback && <p className="fine warn-note">{m.fallback}</p>}
              {m.truncated && (
                <p className="fine warn-note">
                  Cevap ayrılan sınırda kesildi; soruyu daraltmak sonucu
                  iyileştirir.
                </p>
              )}
              {m.tool && !m.streaming && (
                <>
                  <details className="evidence">
                    <summary>Kaynağı gör · {m.duration_ms} ms</summary>
                    <p>
                      {stamp(m.as_of)}
                      <br />
                      Kaynak: mevcut PostgreSQL kayıtları.
                      <br />
                      Motor: {m.engine}
                      {m.effort ? ` · effort ${m.effort}` : ""}
                    </p>
                    {m.calls?.length > 0 ? (
                      <ol className="tool-trace">
                        {m.calls.map((c, j) => (
                          <li key={j} className={c.ok ? "ok" : "failed"}>
                            {toolLabels[c.name] || c.name} · {c.duration_ms} ms
                            · {c.ok ? "başarılı" : "hata"}
                          </li>
                        ))}
                      </ol>
                    ) : (
                      <p>Uygulama aracı: {m.tool}</p>
                    )}
                    {m.data?.run && (
                      <p>
                        Run #{m.data.run.run_id} · {modeLabel(m.data.run)}
                      </p>
                    )}
                    {m.usage && (
                      <p>
                        Token: {m.usage.input_tokens} girdi ·{" "}
                        {m.usage.output_tokens} çıktı
                        {m.usage.cache_read_input_tokens > 0
                          ? ` · ${m.usage.cache_read_input_tokens} cache`
                          : ""}
                        {m.turns > 1 ? ` · ${m.turns} model turu` : ""}
                      </p>
                    )}
                  </details>
                  <button
                    className="text-button"
                    onClick={() =>
                      onNavigate(
                        m.tool === "get_strategy" ? "strategies" : "overview",
                      )
                    }
                  >
                    İlgili görünümü aç <Icon name="arrow" />
                  </button>
                </>
              )}
            </article>
          ))}
        </div>
        {busy && (
          <p className="query-status" role="status">
            {stage ? `${stage}…` : "Soru değerlendiriliyor…"}
          </p>
        )}
      </div>
      {newReply && (
        <button className="new-reply" onClick={scroll}>
          Yeni cevap ↓
        </button>
      )}
      <form
        className="chat-composer"
        onSubmit={(e) => {
          e.preventDefault();
          send(draft);
        }}
      >
        <label htmlFor="question">
          {selected || "İzlenen pariteler"} hakkında sor
        </label>
        <div>
          <textarea
            id="question"
            ref={input}
            value={draft}
            maxLength={1000}
            rows={2}
            placeholder="Örn. Hacim neden yetersiz?"
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send(draft);
              }
            }}
          />
          <button
            className="primary send"
            disabled={busy || draft.trim().length < 2}
            aria-label="Soruyu gönder"
          >
            <Icon name="arrow" />
          </button>
        </div>
        <span className="fine">Enter gönderir · Shift + Enter yeni satır</span>
      </form>
    </aside>
  );
}
function Connection({ session, connection, onSession, error }) {
  const [token, setToken] = useState(""),
    [busy, setBusy] = useState(false),
    [failure, setFailure] = useState("");
  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setFailure("");
    try {
      await login(token);
      setToken("");
      await onSession();
    } catch (err) {
      setFailure(err.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel connection">
      <span className="eyebrow">OKX bağlantısı</span>
      <h2>Hesabın kontrolü sende.</h2>
      <p>
        Piyasa keşfi anahtar gerektirmez. Özel hesap kayıtları için bu
        uygulamanın operatör oturumunu aç.
      </p>
      {!session?.authenticated ? (
        <form onSubmit={submit}>
          <label htmlFor="operator">Operatör erişim kodu</label>
          <input
            id="operator"
            type="password"
            autoComplete="current-password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            required
          />
          <p className="fine">
            OKX API anahtarını buraya yazma. Bu kod yerel uygulama erişimi
            içindir.
          </p>
          <button className="primary" disabled={busy || !token}>
            {busy ? "Oturum açılıyor…" : "Oturumu aç"}
          </button>
          {!session?.configured && (
            <p className="callout">
              API'de operatör erişimi henüz yapılandırılmamış. Kurulum adımı
              README'de.
            </p>
          )}
        </form>
      ) : (
        <>
          <span className="badge success">Operatör oturumu açık</span>
          <dl className="connection-grid">
            <dt>Hesap</dt>
            <dd>{connection?.alias || "Kayıt bekleniyor"}</dd>
            <dt>Son başlangıç kontrolü</dt>
            <dd>{stamp(connection?.last_check)}</dd>
            <dt>Başlangıç mutabakatı</dt>
            <dd>
              {connection?.reconciled_at_start === true
                ? "Temiz"
                : connection?.reconciled_at_start === false
                  ? "Tamamlanmadı"
                  : "Doğrulanmadı"}
            </dd>
            <dt>İzinler</dt>
            <dd>{connection?.permissions || "Doğrulanmadı"}</dd>
          </dl>
          <div className="callout">
            <strong>Anahtar saklama</strong>
            <p>{connection?.storage || "Saklama bilgisi alınamadı."}</p>
          </div>
          <button
            className="secondary"
            onClick={async () => {
              await logout();
              await onSession();
            }}
          >
            Operatör oturumunu kapat
          </button>
          <p className="fine">
            Oturumu kapatmak çalışan stratejiyi veya borsadaki emirleri
            durdurmaz.
          </p>
        </>
      )}
      {(failure || error) && (
        <p role="alert" className="error">
          {failure || error}
        </p>
      )}
      <details className="integration">
        <summary>Entegrasyon ayrıntıları</summary>
        <p>
          Bu ekran ATK ile worker'ın topladığı PostgreSQL kayıtlarını okur. Her
          soruda borsaya yeni bir çağrı yapılmaz.
        </p>
        <p>
          Kalıcı ATK araç çağrı izi henüz tutulmuyor; doğrulanmış araç sayısı bu
          sürümde hesaplanmıyor. Kanıt matrisi geliştirme raporunda.
        </p>
      </details>
    </section>
  );
}

const modeBadge = (mode) =>
  mode === "SHADOW" ? "SHADOW · Simülasyon" : "REPLAY · Geçmiş veri";
const signedR = (v) =>
  v === null || v === undefined ? "—" : `${v > 0 ? "+" : ""}${fmt(v, 3)} R`;

function EquityCurve({ points = [] }) {
  if (!points.length)
    return (
      <Empty title="Henüz kapanmış işlem yok">
        Equity curve ilk simüle işlem kapandığında oluşacak.
      </Empty>
    );
  const series = [{ return_pct: 0 }, ...points];
  const values = series.map((p) => +p.return_pct || 0);
  const low = Math.min(...values, 0);
  const high = Math.max(...values, 0);
  const spread = Math.max(high - low, 0.01);
  const x = (i) => 24 + (i / Math.max(series.length - 1, 1)) * 752;
  const y = (v) => 190 - ((v - low) / spread) * 150;
  const line = series.map((p, i) => `${x(i)},${y(+p.return_pct || 0)}`).join(" ");
  const zeroY = y(0);
  return (
    <div className="equity-chart">
      <svg viewBox="0 0 800 220" role="img" aria-label="Simüle kümülatif getiri eğrisi">
        <line x1="24" y1={zeroY} x2="776" y2={zeroY} className="zero-line" />
        <polyline points={line} className="equity-line" />
        <text x="24" y="212">0%</text>
        <text x="776" y="212" textAnchor="end">
          {fmt(values.at(-1), 3)}%
        </text>
      </svg>
    </div>
  );
}

function Backtest({ session, onConnect }) {
  const [hours, setHours] = useState(48);
  const [report, setReport] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!session?.authenticated) return;
    let active = true;
    setBusy(true);
    getBacktest(hours)
      .then((data) => {
        if (active) {
          setReport(data);
          setError("");
        }
      })
      .catch((e) => active && setError(e.message))
      .finally(() => active && setBusy(false));
    return () => {
      active = false;
    };
  }, [hours, session?.authenticated]);

  if (!session?.authenticated)
    return (
      <section className="panel experiment-empty">
        <div className="large-icon"><Icon name="backtest" width="32" height="32" /></div>
        <h2>Backtest kayıtlı adayları okur.</h2>
        <p>Geçmiş simülasyonu görmek için operatör oturumunu aç.</p>
        <button className="primary" onClick={onConnect}>Operatör oturumunu aç</button>
      </section>
    );
  if (!report)
    return (
      <section className="panel">
        <Empty title={error ? "Backtest çalışmadı" : "Backtest hesaplanıyor"}>
          {error || "Kayıtlı adaylar ve 5 dakikalık mumlar yürütülüyor."}
        </Empty>
      </section>
    );

  const m = report.metrics;
  const result = report.result;
  const closed = result.trades
    .filter((trade) => trade.status === "CLOSED")
    .sort((a, b) => new Date(b.closed_at) - new Date(a.closed_at));
  return (
    <>
      <section className="panel backtest-hero">
        <div className="section-head">
          <div>
            <span className="eyebrow">{report.policy_version}</span>
            <h2>Geçmiş performans özeti</h2>
          </div>
          <div className="range-buttons" role="group" aria-label="Backtest dönemi">
            {[12, 24, 48].map((value) => (
              <button
                key={value}
                className={hours === value ? "selected" : ""}
                onClick={() => setHours(value)}
                disabled={busy}
              >
                {value} saat
              </button>
            ))}
          </div>
        </div>
        <div className={`backtest-return ${m.net_return_pct >= 0 ? "pos" : "neg"}`}>
          <span>Net simüle getiri</span>
          <strong>{m.net_return_pct > 0 ? "+" : ""}{fmt(m.net_return_pct, 3)}%</strong>
          <small>{signedR(m.net_r)} · {m.closed_trades} kapanmış işlem</small>
        </div>
        <p className="fine">
          {stamp(report.window.from)} — {stamp(report.window.to)} · {report.coverage.candidate_episodes} setup
          episode’u · {report.coverage.instruments.length} parite
        </p>
      </section>

      <div className="metrics backtest-metrics">
        <Metric label="Kazanma oranı" value={fmt(m.win_rate_pct, 1)} unit="%" detail={`${result.winners} kazanan · ${result.losers} kaybeden`} />
        <Metric label="Profit factor" value={m.profit_factor_infinite ? "∞" : fmt(m.profit_factor, 2)} detail="Brüt kazanç / brüt kayıp" />
        <Metric label="Max drawdown" value={fmt(m.max_drawdown_pct, 3)} unit="%" detail="Kapanmış işlemler üzerinden" />
        <Metric label="Ortalama işlem" value={signedR(m.average_trade_r)} detail={`${result.open_trades} açık gözlem sonuca dahil değil`} />
      </div>

      <section className="panel">
        <div className="section-head">
          <div><span className="eyebrow">Equity curve</span><h2>Kümülatif yüzde getiri</h2></div>
          <span className="badge">Simülasyon</span>
        </div>
        <EquityCurve points={m.equity_curve} />
      </section>

      <section className="panel">
        <div className="section-head">
          <div><span className="eyebrow">İşlem dökümü</span><h2>Geçmiş sinyaller</h2></div>
          <span className="badge">{closed.length} kapanmış</span>
        </div>
        {closed.length ? (
          <div className="table-scroll">
            <table>
              <thead><tr><th>Parite</th><th>Giriş</th><th>Çıkış</th><th>Net sonuç</th><th>Durum</th></tr></thead>
              <tbody>
                {closed.map((trade) => (
                  <tr key={trade.decision_id}>
                    <td>{trade.inst_id}</td>
                    <td>{fmt(trade.entry_px, 5)}<small className="fine"> · {stamp(trade.entry_at)}</small></td>
                    <td>{stamp(trade.closed_at)}</td>
                    <td className={trade.net_r > 0 ? "pos" : trade.net_r < 0 ? "neg" : ""}>{signedR(trade.net_r)}</td>
                    <td>{trade.ambiguous ? "Belirsiz mum · stop" : trade.legs.at(-1)?.reason || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <Empty title="Kapanmış işlem yok">Seçilen dönemde sonuçlanmış simüle işlem bulunamadı.</Empty>}
        <ul className="fine backtest-limits">
          {report.limits.map((limit) => <li key={limit}>{limit}</li>)}
        </ul>
      </section>
    </>
  );
}

function RuleDiff({ diff }) {
  if (!diff?.length) return null;
  return (
    <ul className="rule-diff">
      {diff.map((d) => (
        <li key={d.key}>
          <span>{d.label}</span>
          <s>{d.before}</s>
          <Icon name="arrow" width="16" height="16" />
          <strong>{d.after}</strong>
        </li>
      ))}
    </ul>
  );
}

// One simulated leg. Every figure here is simulated: the label says so once, at
// the top, rather than being implied by its absence.
function LegCard({ leg, kind }) {
  const r = leg?.result;
  if (!r) return null;
  const open = r.open_trades > 0;
  return (
    <article className={`leg-card ${kind}`}>
      <header>
        <span className="eyebrow">
          {kind === "baseline" ? "Baseline" : "Alternatif"}
        </span>
        <h3>{leg.version_label}</h3>
        <span className={`badge ${leg.status === "RUNNING" ? "" : "muted"}`}>
          {leg.status === "RUNNING" ? "Çalışıyor" : "Sonlandırıldı"}
        </span>
      </header>
      <div className="leg-headline">
        <div>
          <span>Net sonuç (simüle)</span>
          <strong className={r.net_r > 0 ? "pos" : r.net_r < 0 ? "neg" : ""}>
            {signedR(r.net_r)}
          </strong>
          <small>
            {r.closed_trades} kapanmış gözlem
            {open ? ` · ${r.open_trades} açık (sonuç sayılmaz)` : ""}
          </small>
        </div>
        <div>
          <span>Ücret yükü</span>
          <strong>{signedR(r.fees_r === null ? null : -r.fees_r)}</strong>
          <small>Brüt {signedR(r.gross_r)}</small>
        </div>
      </div>
      <dl className="leg-grid">
        <dt>Kaydedilen aday</dt>
        <dd>{r.candidates_seen}</dd>
        <dt>Kuralı geçen</dt>
        <dd>{r.entries_qualified}</dd>
        <dt>Girilen</dt>
        <dd>{r.entries_taken}</dd>
        <dt>Pozisyon doluyken atlanan</dt>
        <dd>{r.entries_skipped_busy}</dd>
        <dt>Kazanan / kaybeden</dt>
        <dd>
          {r.winners} / {r.losers}
        </dd>
        <dt>Belirsiz mum</dt>
        <dd>{r.ambiguous_trades}</dd>
      </dl>
      {r.trades?.length ? (
        <details className="leg-trades">
          <summary>Simüle işlemler ({r.trades.length})</summary>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Parite</th>
                  <th>Giriş</th>
                  <th>Sonuç</th>
                  <th>Çıkış bacakları</th>
                </tr>
              </thead>
              <tbody>
                {r.trades.map((t) => (
                  <tr key={t.decision_id}>
                    <td>
                      {t.inst_id}
                      <small className="fine"> · karar #{t.decision_id}</small>
                    </td>
                    <td>
                      {fmt(t.entry_px, 4)}
                      <small className="fine"> · {stamp(t.entry_at)}</small>
                    </td>
                    <td
                      className={
                        t.net_r > 0 ? "pos" : t.net_r < 0 ? "neg" : undefined
                      }
                    >
                      {t.status === "CLOSED" ? (
                        signedR(t.net_r)
                      ) : (
                        <span className="warn-note">Açık · sonuç yok</span>
                      )}
                      {t.ambiguous && (
                        <small className="fine"> · belirsiz mum</small>
                      )}
                    </td>
                    <td>
                      {t.legs.length
                        ? t.legs
                            .map(
                              (l) =>
                                `${
                                  {
                                    tp1: "1. hedef",
                                    tp2: "2. hedef",
                                    stop: "stop",
                                    stop_ambiguous: "stop (belirsiz)",
                                    time: "süre sonu",
                                  }[l.reason] || l.reason
                                } ${signedR(l.r_multiple)}`,
                            )
                            .join(" · ")
                        : "Henüz çıkış yok"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      ) : (
        <p className="fine">
          Bu kolda henüz giriş yok. Gölge çalışma, başlatıldıktan sonra
          kaydedilen adayları izler.
        </p>
      )}
    </article>
  );
}

function ExperimentDetail({ detail, onStop, onRefresh, busy }) {
  const c = detail.comparison;
  const assumptions = detail.baseline.assumptions || {};
  const running = detail.baseline.status === "RUNNING";
  return (
    <section className="panel experiment-detail">
      <div className="section-head">
        <div>
          <span className="eyebrow">Deney #{detail.experiment_id}</span>
          <h2>{detail.title}</h2>
        </div>
        <span className={`badge ${detail.mode === "SHADOW" ? "shadow" : ""}`}>
          {modeBadge(detail.mode)}
        </span>
      </div>
      <div className={`verdict ${c.state}`} role="status">
        <strong>
          {c.state === "insufficient_evidence"
            ? "Kanıt yetersiz"
            : c.state === "no_difference"
              ? "Fark yok"
              : "Fark gözlendi"}
        </strong>
        <p>{c.headline}</p>
        {c.net_r_delta !== null && (
          <p className="fine">
            Net fark {signedR(c.net_r_delta)} · ortak giriş {c.shared_entries} ·
            yalnız baseline {c.only_baseline_entries.length} · yalnız alternatif{" "}
            {c.only_variant_entries.length}
          </p>
        )}
      </div>
      <div className="leg-pair">
        <LegCard leg={detail.baseline} kind="baseline" />
        <LegCard leg={detail.variant} kind="variant" />
      </div>
      <div className="experiment-meta">
        <dl>
          <dt>Yöntem</dt>
          <dd>{c.method}</dd>
          <dt>Dönem</dt>
          <dd>
            {stamp(detail.baseline.window_from)} —{" "}
            {detail.baseline.window_to
              ? stamp(detail.baseline.window_to)
              : "açık (gözlem sürüyor)"}
          </dd>
          <dt>Veri çözünürlüğü</dt>
          <dd>{assumptions.resolution_note}</dd>
          <dt>Maliyet varsayımı</dt>
          <dd>
            Taker {fmt(+assumptions.taker_fee_rate * 10000, 1)} bp · slippage{" "}
            {fmt(assumptions.slippage_bps, 1)} bp · simüle sermaye{" "}
            {fmt(assumptions.equity_quote)} USDT. {assumptions.fee_note}
          </dd>
          <dt>Son değerlendirme</dt>
          <dd>
            {stamp(detail.baseline.last_evaluated_at)}
            {assumptions.window_note ? ` · ${assumptions.window_note}` : ""}
          </dd>
        </dl>
        <ul className="fine">
          {c.limits.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      </div>
      <div className="experiment-controls">
        <button
          className="secondary"
          disabled={busy === "refresh"}
          onClick={onRefresh}
        >
          {busy === "refresh" ? "Kontrol ediliyor…" : "Durumu kontrol et"}
        </button>
        {running && (
          <button
            className="danger-outline"
            disabled={busy === "stop"}
            onClick={onStop}
          >
            {busy === "stop" ? "Sonlandırılıyor…" : "Gölge çalışmayı sonlandır"}
          </button>
        )}
        <span className="fine">
          Bu çalışma borsaya emir göndermez ve canlı bakiyeyi kullanmaz.
          Sonlandırmak canlı pozisyon kapatmaz.
        </span>
      </div>
    </section>
  );
}

function DraftForm({ baseline, catalogue, onCreate, busy, onAsk }) {
  const [key, setKey] = useState("exit.breakeven_r");
  const [value, setValue] = useState("");
  const [off, setOff] = useState(false);
  const rule = catalogue.find((c) => c.key === key);
  useEffect(() => {
    setValue(rule?.current ?? "");
    setOff(rule?.current === null);
  }, [key]);
  const sections = ["Çıkış kuralı", "Giriş kuralı"];
  return (
    <form
      className="draft-form"
      onSubmit={(e) => {
        e.preventDefault();
        onCreate(baseline.version_id, key, off ? null : Number(value));
      }}
    >
      <div className="draft-fields">
        <label htmlFor="rule">
          Değiştirilecek kural
          <select
            id="rule"
            value={key}
            onChange={(e) => setKey(e.target.value)}
          >
            {sections.map((s) => (
              <optgroup key={s} label={s}>
                {catalogue
                  .filter((c) => c.section === s)
                  .map((c) => (
                    <option key={c.key} value={c.key}>
                      {c.label}
                    </option>
                  ))}
              </optgroup>
            ))}
          </select>
        </label>
        <label htmlFor="value">
          Yeni değer
          <input
            id="value"
            type="number"
            inputMode="decimal"
            value={off ? "" : value}
            disabled={off}
            min={rule?.minimum ?? undefined}
            max={rule?.maximum ?? undefined}
            step={rule?.step ?? "any"}
            onChange={(e) => setValue(e.target.value)}
            required={!off}
          />
        </label>
      </div>
      <p className="fine">
        {rule?.help} Şu anki değer: <strong>{rule?.current_label}</strong>
        {rule?.minimum !== null && rule?.maximum !== null
          ? ` · izinli aralık ${fmt(rule?.minimum, 2)} – ${fmt(rule?.maximum, 2)}`
          : ""}
      </p>
      {rule?.nullable && (
        <label className="check">
          <input
            type="checkbox"
            checked={off}
            onChange={(e) => setOff(e.target.checked)}
          />
          {rule.null_label}
        </label>
      )}
      <div className="draft-actions">
        <button className="primary" disabled={busy === "draft"}>
          {busy === "draft" ? "Taslak kaydediliyor…" : "Taslağı kaydet"}
        </button>
        <button
          type="button"
          className="text-button"
          onClick={() => onAsk("1R'da stop'u entry'ye çekmeseydik ne olurdu?")}
        >
          Quant'a sor <Icon name="arrow" />
        </button>
      </div>
      <p className="fine">
        Taslak kaydetmek çalışma başlatmaz. Tek seferde tek kural değişir; iki
        kural birden değişirse sonucun hangisinden geldiği söylenemez.
      </p>
    </form>
  );
}

function Experiments({ session, onConnect, onAsk }) {
  const [data, setData] = useState(null);
  const [detail, setDetail] = useState(null);
  const [selected, setSelected] = useState(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const authenticated = session?.authenticated;

  async function load() {
    try {
      const overview = await getExperiments();
      setData(overview);
      setError("");
      if (!selected && overview.experiments.length)
        setSelected(overview.experiments[0].experiment_id);
    } catch (e) {
      setError(e.message);
    }
  }
  useEffect(() => {
    if (authenticated) load();
  }, [authenticated]);
  // The result is a snapshot of a deterministic replay, so polling shows a
  // shadow run picking up candidates as new candles close.
  useEffect(() => {
    if (!selected) return;
    let active = true,
      timer;
    async function poll() {
      try {
        const d = await getExperiment(selected);
        if (active) {
          setDetail(d);
          setError("");
        }
      } catch (e) {
        if (active) setError(e.message);
      }
      if (active) timer = setTimeout(poll, 20000);
    }
    poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [selected]);

  async function createDraftVersion(parent, key, value) {
    setBusy("draft");
    setError("");
    try {
      await createDraft(parent, key, value);
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy("");
    }
  }
  async function start(versionId, mode) {
    setBusy(`start:${versionId}:${mode}`);
    setError("");
    try {
      const started = await startExperiment(versionId, mode);
      setDetail(started);
      setSelected(started.experiment_id);
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy("");
    }
  }
  async function refresh() {
    setBusy("refresh");
    try {
      setDetail(await getExperiment(selected));
      setError("");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy("");
    }
  }
  async function stopShadow() {
    setBusy("stop");
    try {
      await stopExperimentRun(detail.baseline.exp_run_id);
      await stopExperimentRun(detail.variant.exp_run_id);
      setDetail(await getExperiment(selected));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy("");
    }
  }

  if (!authenticated)
    return (
      <section className="panel experiment-empty">
        <div className="large-icon">
          <Icon name="experiment" width="32" height="32" />
        </div>
        <h2>Deneyler kendi kayıtlarını okur.</h2>
        <p>
          Baseline ile alternatifi karşılaştırmak için stratejinin karar
          kayıtlarına erişim gerekir. Operatör oturumunu aç.
        </p>
        <button className="primary" onClick={onConnect}>
          Operatör oturumunu aç <Icon name="arrow" />
        </button>
      </section>
    );
  if (!data)
    return (
      <section className="panel">
        <Empty
          title={error ? "Deney servisi okunamadı" : "Deneyler yükleniyor"}
        >
          {error || "Kayıtlı sürümler ve çalışmalar getiriliyor."}
        </Empty>
      </section>
    );

  const drafts = data.versions.filter((v) => !v.is_baseline);
  return (
    <>
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      <section className="panel experiment-intro">
        <div className="experiment-steps">
          <span>01 · Kuralı değiştir</span>
          <span>02 · Gölge/replay çalıştır</span>
          <span>03 · Kanıtı karşılaştır</span>
        </div>
        <h2>Bir değişiklik. Bir deney.</h2>
        <p>
          Başlangıç stratejisini kopyala, tek kuralı değiştir ve iki kolu aynı
          kayıtlar üzerinde, sermaye ayırmadan karşılaştır.
        </p>
        <div className="baseline-strip">
          <div>
            <span className="eyebrow">Baseline sürüm</span>
            <strong>{data.baseline.label}</strong>
          </div>
          <details>
            <summary>Kuralları gör</summary>
            <ol className="rules">
              {data.baseline.rules.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ol>
          </details>
        </div>
        <DraftForm
          baseline={data.baseline}
          catalogue={data.catalogue}
          onCreate={createDraftVersion}
          busy={busy}
          onAsk={onAsk}
        />
      </section>

      <section className="panel">
        <div className="section-head">
          <div>
            <span className="eyebrow">Taslak sürümler</span>
            <h2>Neyi denemek istiyorsun?</h2>
          </div>
        </div>
        {drafts.length ? (
          <div className="draft-list">
            {drafts.map((v) => (
              <article key={v.version_id} className="draft-card">
                <header>
                  <div>
                    <strong>{v.label}</strong>
                    <small className="fine">
                      Sürüm #{v.version_id} · {stamp(v.created_at)}
                    </small>
                  </div>
                  <span className="badge muted">Taslak</span>
                </header>
                <RuleDiff diff={v.diff} />
                <div className="draft-actions">
                  <button
                    className="primary"
                    disabled={busy.startsWith("start")}
                    onClick={() => start(v.version_id, "SHADOW")}
                  >
                    {busy === `start:${v.version_id}:SHADOW`
                      ? "Başlatılıyor…"
                      : "Gölge çalıştır"}
                  </button>
                  <button
                    className="secondary"
                    disabled={busy.startsWith("start")}
                    onClick={() => start(v.version_id, "REPLAY")}
                  >
                    {busy === `start:${v.version_id}:REPLAY`
                      ? "Başlatılıyor…"
                      : "Kayıtlı dönemde dene"}
                  </button>
                  <details className="draft-rules">
                    <summary>Bu sürümün kuralları</summary>
                    <ol className="rules">
                      {v.rules.map((r) => (
                        <li key={r}>{r}</li>
                      ))}
                    </ol>
                  </details>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <Empty title="Henüz taslak yok">
            Yukarıdan bir kuralı değiştirerek ilk alternatifini oluştur.
          </Empty>
        )}
        <p className="fine">
          Gölge, başlatıldıktan sonra kaydedilen adayları izler. Kayıtlı dönem,
          arşivde duran son {48} saati yeniden değerlendirir; ikisi aynı şey
          değildir ve ayrı etiketlenir.
        </p>
      </section>

      {data.experiments.length > 0 && (
        <section className="panel">
          <div className="section-head">
            <div>
              <span className="eyebrow">Çalışmalar</span>
              <h2>Başlatılan deneyler</h2>
            </div>
          </div>
          <div className="experiment-list">
            {data.experiments.map((e) => (
              <button
                key={e.experiment_id}
                className={selected === e.experiment_id ? "selected" : ""}
                onClick={() => setSelected(e.experiment_id)}
              >
                <strong>{e.title}</strong>
                <span className="badge">{modeBadge(e.mode)}</span>
                <small>
                  #{e.experiment_id} · {stamp(e.created_at)} ·{" "}
                  {e.variant_status === "RUNNING"
                    ? "çalışıyor"
                    : "sonlandırıldı"}
                </small>
              </button>
            ))}
          </div>
        </section>
      )}

      {detail && detail.experiment_id === selected && (
        <ExperimentDetail
          detail={detail}
          busy={busy}
          onRefresh={refresh}
          onStop={stopShadow}
        />
      )}
    </>
  );
}

export default function App() {
  const [view, setView] = useState("overview"),
    [market, setMarket] = useState(null),
    [data, setData] = useState(null),
    [strategy, setStrategy] = useState(null),
    [session, setSession] = useState(null);
  const [selected, setSelected] = useState("BTC-USDT"),
    [candles, setCandles] = useState([]),
    [bar, setBar] = useState("5m"),
    [error, setError] = useState(""),
    [privateError, setPrivateError] = useState(""),
    [chartError, setChartError] = useState(""),
    [chatOpen, setChatOpen] = useState(false);
  const chatButton = useRef(null);
  const chartRequest = useRef(0);
  async function refreshSession() {
    const s = await getSession();
    setSession(s);
    if (!s.authenticated) {
      setData(null);
      setPrivateError("");
    }
  }
  useEffect(() => {
    refreshSession().catch((e) => setError(e.message));
    getStrategy()
      .then(setStrategy)
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    let active = true;
    let timer;
    async function poll() {
      try {
        const m = await getMarket();
        if (active) {
          setMarket(m);
          setError("");
        }
      } catch (e) {
        if (active) setError(e.message);
      }
      if (active) timer = setTimeout(poll, 10000);
    }
    poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, []);
  useEffect(() => {
    if (!session?.authenticated) return;
    let active = true,
      timer;
    async function poll() {
      try {
        const w = await getWorkspace();
        if (active) {
          setData(w);
          setPrivateError("");
        }
      } catch (e) {
        if (active) setPrivateError(e.message);
      }
      if (active) timer = setTimeout(poll, 10000);
    }
    poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [session?.authenticated]);
  useEffect(() => {
    let active = true,
      timer;
    const requestId = ++chartRequest.current;
    setCandles([]);
    setChartError("");
    async function poll() {
      try {
        const c = await getCandles(selected, bar);
        if (active && requestId === chartRequest.current) {
          setCandles(c);
          setChartError("");
        }
      } catch (e) {
        if (active) setChartError(e.message);
      }
      if (active) timer = setTimeout(poll, 10000);
    }
    poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [selected, bar]);
  const current = market?.instruments.find((i) => i.inst_id === selected),
    run = data?.run,
    ledger = data?.ledger,
    funnel = data?.funnel;
  const last = candles.at(-1);
  function ask(message) {
    setChatOpen(true);
    window.dispatchEvent(new CustomEvent("quant-ask", { detail: message }));
  }
  function closeChat() {
    setChatOpen(false);
    chatButton.current?.focus();
  }
  return (
    <div className="quant-app">
      <a className="skip-link" href="#main">
        İçeriğe geç
      </a>
      <nav className="sidebar" aria-label="Ana gezinme">
        <a
          href="#"
          className="brand"
          onClick={(e) => {
            e.preventDefault();
            setView("overview");
          }}
        >
          <span className="brand-mark">
            Q<span>·</span>
          </span>
          <span>
            ThatsMyQuant<small>Kişisel quant çalışma alanı</small>
          </span>
        </a>
        <div className="nav-items">
          {views.map((v) => (
            <button
              key={v.id}
              className={view === v.id ? "active" : ""}
              aria-current={view === v.id ? "page" : undefined}
              onClick={() => setView(v.id)}
            >
              <Icon name={v.icon} />
              <span>{v.name}</span>
            </button>
          ))}
        </div>
        <div className="nav-bottom">
          <p>
            Fikrini kurala.
            <br />
            Kuralını kanıta dönüştür.
          </p>
          <button
            aria-label="OKX bağlantısı"
            className={view === "connection" ? "active" : ""}
            onClick={() => setView("connection")}
            aria-current={view === "connection" ? "page" : undefined}
          >
            <Icon name="link" />
            <span>OKX bağlantısı</span>
          </button>
          <span className="local-label">Yerel operatör · İlk ürün sürümü</span>
        </div>
      </nav>
      <div className="app-body">
        <header className="topbar">
          <span>
            {views.find((v) => v.id === view)?.name || "OKX bağlantısı"}
          </span>
          <div>
            <span className="source-label">OKX TR</span>
            <span className={`badge ${run?.mode === "live" ? "live" : ""}`}>
              {modeLabel(run)}
            </span>
            <button
              className="account-button"
              onClick={() => setView("connection")}
            >
              {session?.authenticated ? "Operatör" : "Oturum aç"}
              <span className="account-avatar">
                {session?.authenticated ? "O" : "↗"}
              </span>
            </button>
          </div>
        </header>
        <div className="workspace">
          <main id="main" tabIndex={-1}>
            <div className="page-heading">
              <div>
                <span className="eyebrow">
                  {view === "overview"
                    ? "Piyasa çalışma alanın"
                    : "ThatsMyQuant"}
                </span>
                <h1>
                  {view === "overview"
                    ? "Önce anla. Sonra karar ver."
                    : view === "strategies"
                      ? "Kuralların, açık ve ölçülebilir."
                      : view === "backtest"
                        ? "Geçmişi ölç. Sonucu göster."
                      : view === "experiments"
                        ? "Bir değişiklik. Bir deney."
                        : "Güvenilir bir bağlantı."}
                </h1>
              </div>
              <button
                className="chat-toggle secondary"
                ref={chatButton}
                aria-expanded={chatOpen}
                onClick={() => setChatOpen(!chatOpen)}
              >
                <Icon name="chat" />
                Quant'a sor
              </button>
            </div>
            {(error || privateError) && (
              <div className="error" role="alert">
                {error || privateError}{" "}
                {market &&
                  `Son başarılı veri: ${stamp(market.as_of)}. Gösterilen değerler eski olabilir.`}
              </div>
            )}
            {view === "overview" && (
              <>
                <div className="market-summary">
                  <span
                    className={`status-dot ${!error && current && !current.stale ? "fresh" : ""}`}
                  />
                  <p>
                    {current
                      ? `${current.regime}. ${current.reasons[0] || "Kurulum verisi bekleniyor"}.`
                      : "Piyasa kayıtları alınıyor…"}
                  </p>
                  <time>{stamp(market?.as_of)}</time>
                </div>
                <div className="metrics">
                  <Metric
                    label="Son işlem fiyatı"
                    value={fmt(current?.px)}
                    unit="USDT"
                    detail={
                      current?.ts
                        ? `${selected} · ${stamp(current.ts)}`
                        : "Gerçek piyasa verisi bekleniyor"
                    }
                  />
                  <Metric
                    label="Göreli hacim"
                    value={fmt(current?.features?.rvol)}
                    unit="×"
                    detail={`5m kapanış · Teyit eşiği ${fmt(strategy?.params?.min_rvol, 2)}${current?.decision_stale ? " · Ölçüm eski" : ""}`}
                  />
                  <Metric
                    label="Açık risk baz tutarı"
                    value={fmt(ledger?.open_risk_quote)}
                    unit="USDT"
                    detail={
                      ledger
                        ? `${ledger.open_positions} pozisyon · ilk risk bazı`
                        : "Hesap görünümü için oturum aç"
                    }
                  />
                  <Metric
                    label="Kayıtlı net sonuç"
                    value={fmt(ledger?.realized_net_quote)}
                    unit="USDT"
                    detail={
                      ledger
                        ? `${ledger.closed_positions} kapalı pozisyon · ledger`
                        : "Canlı ve simüle sonuçlar ayrılır"
                    }
                  />
                </div>
                <section className="panel chart-panel">
                  <div className="chart-head">
                    <div
                      className="instrument-tabs"
                      role="group"
                      aria-label="Parite"
                    >
                      {(market?.instruments.length
                        ? market.instruments.map((i) => i.inst_id)
                        : ["BTC-USDT", "ETH-USDT", "SOL-USDT"]
                      ).map((i) => (
                        <button
                          key={i}
                          aria-pressed={selected === i}
                          className={selected === i ? "selected" : ""}
                          onClick={() => setSelected(i)}
                        >
                          {i.split("-")[0]}
                          <span>/ USDT</span>
                        </button>
                      ))}
                    </div>
                    <select
                      aria-label="Grafik zaman ölçeği"
                      value={bar}
                      onChange={(e) => setBar(e.target.value)}
                    >
                      <option value="1m">1 dakika</option>
                      <option value="5m">5 dakika</option>
                      <option value="15m">15 dakika</option>
                    </select>
                  </div>
                  <div className="chart-caption">
                    <span>
                      Fiyat & hacim <small>· OKX TR · USDT</small>
                    </span>
                    <span>
                      {current?.stale
                        ? "Veri eski"
                        : current
                          ? "Son trade güncel"
                          : "Veri bekleniyor"}{" "}
                      · Spread{" "}
                      {current?.book_stale
                        ? "— (eski)"
                        : fmt(current?.spread_bps)}{" "}
                      bp
                    </span>
                  </div>
                  {chartError && (
                    <p role="alert" className="error">
                      {chartError}
                    </p>
                  )}
                  <Chart
                    key={`${selected}:${bar}`}
                    candles={candles}
                    fills={ledger?.fills}
                    bar={bar}
                    instrument={`${selected}:${bar}`}
                    markers={{
                      level: current?.features?.setup?.level,
                      stop: current?.features?.setup?.pullback_low,
                    }}
                  />
                  {!candles.length && (
                    <p className="chart-empty">
                      {chartError
                        ? "Grafik verisi alınamadı."
                        : "Mum kaydı bekleniyor."}
                    </p>
                  )}
                  <div className="chart-footer">
                    <span>
                      Son mum: O {fmt(last?.open)} · H {fmt(last?.high)} · L{" "}
                      {fmt(last?.low)} · C {fmt(last?.close)} · V{" "}
                      {fmt(last?.volume, 0)} USDT
                    </span>
                    <span>
                      {last
                        ? last.confirm
                          ? "Kapanmış mum"
                          : "Oluşan mum · sinyal değildir"
                        : "—"}
                    </span>
                  </div>
                </section>
                <div className="lower-grid">
                  <StrategyCard strategy={strategy} run={run} onAsk={ask} />
                  <section className="panel">
                    <div className="section-head">
                      <div>
                        <span className="eyebrow">Karar günlüğü</span>
                        <h2>Neyi bekliyoruz?</h2>
                      </div>
                      <button
                        className="text-button"
                        onClick={() => ask("Neden işlem açmadık?")}
                      >
                        İncele <Icon name="arrow" />
                      </button>
                    </div>
                    {session?.authenticated ? (
                      <DecisionList data={data?.decisions} />
                    ) : (
                      <Empty title="Stratejinin kararlarını gör">
                        <button
                          className="text-button"
                          onClick={() => setView("connection")}
                        >
                          Operatör oturumunu aç →
                        </button>
                      </Empty>
                    )}
                  </section>
                </div>
                {funnel && (
                  <section className="panel funnel">
                    <div>
                      <h2>
                        Karar akışı{" "}
                        <span className="badge">Run #{run.run_id}</span>
                      </h2>
                      <p>
                        {stamp(funnel.since)} — {stamp(funnel.until)}
                      </p>
                    </div>
                    <div className="funnel-counts">
                      <span>
                        <strong>{funnel.evaluations}</strong> değerlendirme
                      </span>
                      <span>
                        <strong>{funnel.unique_candles}</strong> farklı
                        parite/mum
                      </span>
                      <span>
                        <strong>{funnel.episodes}</strong> kurulum bölümü
                      </span>
                      <span>
                        <strong>{funnel.confirmed}</strong> onaylı değerlendirme
                      </span>
                    </div>
                    <p className="fine">
                      Tekrar değerlendirmeler bağımsız fırsat değildir. Çalışma
                      durumu:{" "}
                      {run.health === "recent_decisions"
                        ? "Yakın zamanda karar üretti"
                        : run.health === "stopped"
                          ? "Durduruldu"
                          : "Heartbeat doğrulanamıyor"}
                      .
                    </p>
                  </section>
                )}
                {ledger && (
                  <section className="panel">
                    <h2>Gerçekleşen işlemler</h2>
                    <p className="fine">
                      {ledger.scope}. {ledger.limitation}
                    </p>
                    {ledger.fills.length ? (
                      <div className="table-scroll">
                        <table>
                          <thead>
                            <tr>
                              <th>Parite</th>
                              <th>Yön</th>
                              <th>Fiyat</th>
                              <th>Miktar</th>
                              <th>Ücret</th>
                              <th>Zaman</th>
                            </tr>
                          </thead>
                          <tbody>
                            {ledger.fills.map((f, i) => (
                              <tr key={i}>
                                <td>{f.inst_id}</td>
                                <td>{f.side === "buy" ? "Alış" : "Satış"}</td>
                                <td>{fmt(f.px)} USDT</td>
                                <td>{fmt(f.qty, 8)}</td>
                                <td>
                                  {fmt(f.fee, 8)} {f.fee_ccy}
                                </td>
                                <td>{stamp(f.ts)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <Empty title="Henüz gerçekleşmiş işlem yok">
                        Sinyal ve giriş niyeti, gerçekleşmiş işlem olarak
                        gösterilmez.
                      </Empty>
                    )}
                  </section>
                )}
              </>
            )}
            {view === "strategies" && (
              <>
                <StrategyCard
                  strategy={strategy}
                  run={run}
                  onAsk={ask}
                  expanded
                />
                <section className="panel">
                  <h2>Bir fikri deneye dönüştür</h2>
                  <p>
                    Bu stratejiyi kopyala, desteklenen tek bir kuralı değiştir
                    ve alternatifi gölge modda izle. Taslak ayrı bir sürüm
                    olarak kaydedilir.
                  </p>
                  <button
                    className="primary"
                    onClick={() => setView("experiments")}
                  >
                    Deneyler ekranını aç <Icon name="arrow" />
                  </button>
                  <div className="callout">
                    Taslak kaydetmek ve gölge çalıştırmak aktif canlı sürümü,
                    açık pozisyonu veya borsadaki emirleri değiştirmez.
                  </div>
                </section>
              </>
            )}
            {view === "backtest" && (
              <Backtest
                session={session}
                onConnect={() => setView("connection")}
              />
            )}
            {view === "experiments" && (
              <Experiments
                session={session}
                onConnect={() => setView("connection")}
                onAsk={ask}
              />
            )}
            {view === "connection" && (
              <Connection
                session={session}
                connection={data?.connection}
                onSession={refreshSession}
                error={privateError}
              />
            )}
            <footer className="page-footer">
              ThatsMyQuant{" "}
              <span>Ölçümler kayıtlardan. Kararlar kurallardan.</span>
            </footer>
          </main>
          <Chat
            assistant={session?.assistant}
            selected={selected}
            opened={chatOpen}
            onClose={closeChat}
            onNavigate={(v) => {
              setView(v);
              setChatOpen(false);
            }}
          />
        </div>
      </div>
    </div>
  );
}

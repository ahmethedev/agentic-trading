import React, { useEffect, useRef, useState } from "react";
import Chart from "./Chart.jsx";
import {
  askQuant,
  askQuantStream,
  getCandles,
  getMarket,
  getSession,
  getStrategy,
  getWorkspace,
  login,
  logout,
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
                            {toolLabels[c.name] || c.name} · {c.duration_ms} ms ·{" "}
                            {c.ok ? "başarılı" : "hata"}
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
    setCandles([]);
    setChartError("");
    async function poll() {
      try {
        const c = await getCandles(selected, bar);
        if (active) {
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
                    detail={`5m kapanış · Teyit eşiği 1,30${current?.decision_stale ? " · Ölçüm eski" : ""}`}
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
                    Bir sonraki teslim: desteklenen şablondan taslak oluşturma,
                    tek kuralı değiştirme ve ayrı sürüm kaydetme.
                  </p>
                  <div className="callout">
                    Taslak editörü ve gölge başlatma henüz uygulanmadı. Aktif
                    strateji bu görünümden değiştirilemez.
                  </div>
                </section>
              </>
            )}
            {view === "experiments" && (
              <section className="panel experiment-empty">
                <div className="large-icon">
                  <Icon name="experiment" width="32" height="32" />
                </div>
                <h2>İlk deneyin için yer hazır.</h2>
                <p>
                  Baseline ile tek kuralı değişen alternatifi, sermaye ayırmadan
                  karşılaştıracağız.
                </p>
                <div className="experiment-steps">
                  <span>01 · Kuralı seç</span>
                  <span>02 · Gölge izle</span>
                  <span>03 · Kanıtı karşılaştır</span>
                </div>
                <p className="callout">
                  Gölge evaluator bu teslimde bağlı değil. Çalışma veya simüle
                  sonuç üretilmedi.
                </p>
                <button
                  className="secondary"
                  onClick={() => setView("strategies")}
                >
                  Başlangıç kurallarını incele <Icon name="arrow" />
                </button>
              </section>
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

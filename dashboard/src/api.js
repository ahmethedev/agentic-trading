export async function request(path, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(path, {
      ...options,
      signal: controller.signal,
      credentials: "same-origin",
    });
    const body = await response.json();
    if (!response.ok)
      throw new Error(
        typeof body.detail === "string"
          ? body.detail
          : `İstek tamamlanamadı (${response.status}).`,
      );
    return body;
  } catch (error) {
    if (error.name === "AbortError")
      throw new Error("Veri sorgusu zaman aşımına uğradı. Tekrar deneyin.");
    throw error;
  } finally {
    clearTimeout(timer);
  }
}
export const getMarket = () => request("/api/product/market");
export const getWorkspace = () => request("/api/product/workspace");
export const getStrategy = () => request("/api/product/strategy");
export const getSession = () => request("/api/product/session");
export const getCandles = (inst, bar = "5m") =>
  request(
    `/api/candles?inst_id=${encodeURIComponent(inst)}&bar=${bar}&limit=120`,
  );
export const askQuant = (message, inst_id, conversation_id) =>
  request("/api/product/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, inst_id, conversation_id }),
  });

// Streams the answer as it is produced. `onEvent` receives the same events the
// server emits: real tool stages, text deltas, and finally the whole answer.
// Returns the answer, so a caller can await it exactly like askQuant.
export async function askQuantStream(
  { message, inst_id, conversation_id },
  onEvent,
) {
  const response = await fetch("/api/product/ask/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify({ message, inst_id, conversation_id }),
  });
  if (!response.ok || !response.body) {
    let detail = `İstek tamamlanamadı (${response.status}).`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* the error body is not always JSON; the status text stands. */
    }
    throw new Error(detail);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let answer = null;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // SSE frames are separated by a blank line; keep the trailing partial.
    const frames = buffer.split("\n\n");
    buffer = frames.pop();
    for (const frame of frames) {
      const line = frame.split("\n").find((l) => l.startsWith("data: "));
      if (!line) continue;
      const event = JSON.parse(line.slice(6));
      if (event.type === "answer") answer = event.answer;
      else if (event.type === "failed") throw new Error(event.detail);
      else onEvent(event);
    }
  }
  if (!answer) throw new Error("Cevap tamamlanmadan bağlantı kapandı.");
  return answer;
}
export const login = (token) =>
  request("/api/product/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });
export const logout = () =>
  request("/api/product/session", { method: "DELETE" });

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
export const askQuant = (message, inst_id) =>
  request("/api/product/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, inst_id }),
  });
export const login = (token) =>
  request("/api/product/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });
export const logout = () =>
  request("/api/product/session", { method: "DELETE" });

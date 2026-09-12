const get = async (path) => {
  const r = await fetch(path)
  if (!r.ok) throw new Error(`${path}: ${r.status}`)
  return r.json()
}

export const getStatus = () => get('/api/status')
export const getDecisions = (inst, limit = 40) =>
  get(`/api/decisions?limit=${limit}${inst ? `&inst_id=${inst}` : ''}`)
export const getFunnel = (hours = 6) => get(`/api/funnel?hours=${hours}`)
export const getCandles = (inst, bar = '5m') =>
  get(`/api/candles?inst_id=${inst}&bar=${bar}&limit=200`)
export const getFlow = (inst, minutes = 30) =>
  get(`/api/flow?inst_id=${inst}&minutes=${minutes}`)
export const getInstruments = () => get('/api/instruments')
export const getPositions = () => get('/api/positions')

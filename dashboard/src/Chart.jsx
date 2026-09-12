import React, { useEffect, useRef } from 'react'
import { createChart } from 'lightweight-charts'

/** Candles + the level/stop of the most recent setup, drawn from stored data. */
export default function Chart({ candles, markers }) {
  const box = useRef(null)
  const chart = useRef(null)
  const series = useRef(null)

  useEffect(() => {
    if (!box.current) return
    chart.current = createChart(box.current, {
      height: 340,
      layout: { background: { color: 'transparent' }, textColor: '#8b97ab', fontSize: 11 },
      grid: { vertLines: { color: '#1b2230' }, horzLines: { color: '#1b2230' } },
      rightPriceScale: { borderColor: '#262f3f' },
      timeScale: { borderColor: '#262f3f', timeVisible: true, secondsVisible: false },
      crosshair: { mode: 0 },
    })
    series.current = chart.current.addCandlestickSeries({
      upColor: '#26a37b', downColor: '#d0455c',
      borderUpColor: '#26a37b', borderDownColor: '#d0455c',
      wickUpColor: '#26a37b', wickDownColor: '#d0455c',
    })
    const ro = new ResizeObserver(() => {
      if (box.current) chart.current.applyOptions({ width: box.current.clientWidth })
    })
    ro.observe(box.current)
    return () => { ro.disconnect(); chart.current.remove() }
  }, [])

  useEffect(() => {
    if (!series.current || !candles?.length) return
    // Only closed candles carry signal; the forming one is shown but not relied on.
    series.current.setData(candles)
    const lines = []
    if (markers?.level) {
      lines.push(series.current.createPriceLine({
        price: markers.level, color: '#4b8bf5', lineWidth: 1, lineStyle: 2,
        axisLabelVisible: true, title: 'level',
      }))
    }
    if (markers?.stop) {
      lines.push(series.current.createPriceLine({
        price: markers.stop, color: '#d0455c', lineWidth: 1, lineStyle: 2,
        axisLabelVisible: true, title: 'stop',
      }))
    }
    return () => lines.forEach((l) => series.current?.removePriceLine(l))
  }, [candles, markers])

  return <div ref={box} style={{ width: '100%' }} />
}

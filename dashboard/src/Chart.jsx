import React, { useEffect, useRef } from "react";
import { createChart } from "lightweight-charts";

/** Real stored candles and quote volume. Setup levels are not fill markers. */
export default function Chart({
  candles = [],
  markers,
  instrument,
  fills = [],
  bar = "5m",
}) {
  const box = useRef(null),
    api = useRef(null),
    prices = useRef(null),
    volume = useRef(null);
  const fitted = useRef(null);
  useEffect(() => {
    const chart = createChart(box.current, {
      height: 320,
      layout: {
        background: { color: "#FFFFFF" },
        textColor: "#5F6B7A",
        fontFamily: "IBM Plex Sans, sans-serif",
        fontSize: 12,
      },
      grid: { vertLines: { visible: false }, horzLines: { color: "#EEF1F6" } },
      rightPriceScale: {
        borderVisible: false,
        scaleMargins: { top: 0.08, bottom: 0.25 },
      },
      timeScale: {
        borderColor: "#D8DEE8",
        timeVisible: true,
        secondsVisible: false,
      },
      localization: { locale: "tr-TR" },
    });
    api.current = chart;
    prices.current = chart.addCandlestickSeries({
      upColor: "#11785B",
      downColor: "#B93843",
      borderVisible: false,
      wickUpColor: "#11785B",
      wickDownColor: "#B93843",
    });
    volume.current = chart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    });
    chart
      .priceScale("volume")
      .applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    const ro = new ResizeObserver(() =>
      chart.applyOptions({ width: box.current?.clientWidth || 300 }),
    );
    ro.observe(box.current);
    return () => {
      ro.disconnect();
      chart.remove();
      api.current = null;
      prices.current = null;
      volume.current = null;
    };
  }, []);
  useEffect(() => {
    if (!prices.current) return;
    prices.current.setData(candles);
    volume.current.setData(
      candles.map((c) => ({
        time: c.time,
        value: c.volume,
        color: c.close >= c.open ? "#B7D9CD" : "#E9BDC1",
      })),
    );
    if (candles.length && fitted.current !== instrument) {
      api.current.timeScale().fitContent();
      fitted.current = instrument;
    }
    const lines = [];
    if (markers?.level)
      lines.push(
        prices.current.createPriceLine({
          price: +markers.level,
          color: "#3159D9",
          lineWidth: 1,
          lineStyle: 2,
          axisLabelVisible: true,
          title: "Kurulum",
        }),
      );
    if (markers?.stop)
      lines.push(
        prices.current.createPriceLine({
          price: +markers.stop,
          color: "#B93843",
          lineWidth: 1,
          lineStyle: 2,
          axisLabelVisible: true,
          title: "Yapısal stop",
        }),
      );
    return () => lines.forEach((l) => prices.current?.removePriceLine(l));
  }, [candles, markers?.level, markers?.stop, instrument]);
  useEffect(() => {
    if (!prices.current) return;
    const seconds = { "1m": 60, "5m": 300, "15m": 900 }[bar] || 300;
    const times = new Set(candles.map((c) => c.time));
    const points = fills
      .filter((f) => f.inst_id === instrument.split(":")[0])
      .map((f) => ({
        time: Math.floor(new Date(f.ts).getTime() / 1000 / seconds) * seconds,
        position: f.side === "buy" ? "belowBar" : "aboveBar",
        color: f.side === "buy" ? "#11785B" : "#B93843",
        shape: f.side === "buy" ? "arrowUp" : "arrowDown",
        text: f.side === "buy" ? "Alış fill" : "Satış fill",
      }))
      .filter((f) => times.has(f.time))
      .sort((a, b) => a.time - b.time);
    prices.current.setMarkers(points);
  }, [candles, fills, instrument, bar]);
  return (
    <div
      ref={box}
      role="img"
      aria-label={`${instrument} fiyat ve hacim grafiği; sayısal özet aşağıdadır.`}
      className="chart-canvas"
    />
  );
}

import * as echarts from "echarts";
import { useEffect, useRef, useState } from "react";

/** Цвета графиков берутся из CSS-переменных, поэтому тёмная тема — те же токены. */
export function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export function seriesColor(slot: number): string {
  return cssVar(`--series-${(slot % 8) + 1}`);
}

export function chartChrome(): echarts.EChartsOption {
  const ink2 = cssVar("--ink-2");
  const muted = cssVar("--muted");
  const grid = cssVar("--grid");
  return {
    textStyle: { fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif", color: ink2 },
    grid: { left: 8, right: 16, top: 36, bottom: 8, containLabel: true },
    tooltip: {
      backgroundColor: cssVar("--surface"),
      borderColor: cssVar("--border"),
      textStyle: { color: cssVar("--ink"), fontSize: 12 },
    },
    legend: { top: 0, left: 0, icon: "roundRect", itemWidth: 10, itemHeight: 10, textStyle: { color: ink2 } },
    xAxis: { axisLine: { lineStyle: { color: grid } }, axisTick: { show: false }, axisLabel: { color: muted }, splitLine: { show: false } },
    yAxis: { axisLine: { show: false }, axisLabel: { color: muted }, splitLine: { lineStyle: { color: grid } } },
  };
}

function useColorScheme(): string {
  const [scheme, setScheme] = useState(() => (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
  useEffect(() => {
    const mq = matchMedia("(prefers-color-scheme: dark)");
    const on = () => setScheme(mq.matches ? "dark" : "light");
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return scheme;
}

export function Chart({ option, height = 280, onClick }: { option: () => echarts.EChartsOption; height?: number; onClick?: (p: unknown) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const scheme = useColorScheme();
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current, undefined, { renderer: "svg" });
    chart.setOption(option());
    if (onClick) chart.on("click", onClick);
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      chart.dispose();
    };
  }, [option, scheme, onClick]);
  return <div ref={ref} style={{ height, width: "100%" }} />;
}

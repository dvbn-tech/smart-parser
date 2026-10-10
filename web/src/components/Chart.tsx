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

export interface LineSeries {
  name: string;
  color: string;
  data: (number | null)[];
  width?: number;
}

/** Линии по категориальной оси X. Пропуск (null) — разрыв линии, а не ноль. */
export function lineOption(x: string[], series: LineSeries[], fmt: (v: number) => string): echarts.EChartsOption {
  const base = chartChrome();
  return {
    ...base,
    grid: { ...(base.grid as object), top: series.length > 1 ? 40 : 16 },
    legend: series.length > 1 ? base.legend : { show: false },
    tooltip: {
      ...(base.tooltip as object),
      trigger: "axis",
      valueFormatter: (v: unknown) => (v === null || v === undefined ? "нет данных" : fmt(Number(v))),
    },
    xAxis: { ...(base.xAxis as object), type: "category", data: x, boundaryGap: false },
    yAxis: { ...(base.yAxis as object), type: "value", axisLabel: { color: cssVar("--muted"), formatter: (v: number) => fmt(v) } },
    series: series.map((s) => ({
      name: s.name,
      type: "line",
      data: s.data,
      color: s.color,
      symbol: "circle",
      symbolSize: 6,
      showSymbol: x.length <= 40,
      connectNulls: false,
      lineStyle: { width: s.width ?? 2 },
      emphasis: { focus: "series" },
    })),
  };
}

/** Столбцы с опорной линией (напр. ×1,0 — обычный результат автора). */
export function barOption(
  x: string[],
  values: (number | null)[],
  opts: { fmt: (v: number) => string; reference?: number; tooltip?: (i: number) => string; color?: string; highlight?: (v: number) => boolean },
): echarts.EChartsOption {
  const base = chartChrome();
  const accent = opts.color ?? seriesColor(0);
  const muted = cssVar("--muted");
  return {
    ...base,
    grid: { ...(base.grid as object), top: 16 },
    legend: { show: false },
    tooltip: {
      ...(base.tooltip as object),
      trigger: "axis",
      axisPointer: { type: "shadow" },
      formatter: (p: unknown) => {
        const i = (p as { dataIndex: number }[])[0]?.dataIndex ?? 0;
        return opts.tooltip ? opts.tooltip(i) : `${x[i]}: ${values[i] === null ? "нет данных" : opts.fmt(values[i] as number)}`;
      },
    },
    xAxis: { ...(base.xAxis as object), type: "category", data: x, axisLabel: { color: muted, interval: x.length > 10 ? "auto" : 0, hideOverlap: true } },
    yAxis: { ...(base.yAxis as object), type: "value", axisLabel: { color: muted, formatter: (v: number) => opts.fmt(v) } },
    series: [
      {
        type: "bar",
        barMaxWidth: 28,
        data: values.map((v) => ({
          value: v,
          itemStyle: {
            color: v !== null && opts.highlight && !opts.highlight(v) ? cssVar("--grid") : accent,
            borderRadius: [4, 4, 0, 0],
          },
        })),
        markLine:
          opts.reference !== undefined
            ? { symbol: "none", silent: true, label: { show: false }, lineStyle: { color: muted, type: "dashed" }, data: [{ yAxis: opts.reference }] }
            : undefined,
      },
    ],
  };
}

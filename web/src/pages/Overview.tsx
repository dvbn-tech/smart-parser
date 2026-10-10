import { useQuery } from "@tanstack/react-query";
import type { EChartsOption } from "echarts";
import { useCallback, useMemo } from "react";
import { Link } from "react-router-dom";
import { api, type BrandStats, type MediaRow, type Overview } from "../api";
import { Chart, chartChrome, cssVar, seriesColor } from "../components/Chart";
import { Delta, Empty, ErrorBox, KpiTile, Loading, MediaCard, PeriodPicker, SortTable, useParam } from "../components/ui";
import { fmtCompact, fmtInt, fmtPct } from "../format";

function aggregate(rows: BrandStats[]) {
  const reels = rows.reduce((s, b) => s + b.reels, 0);
  const spikes = rows.reduce((s, b) => s + b.spikes, 0);
  const viral = rows.reduce((s, b) => s + b.viral, 0);
  const views = rows.reduce((s, b) => s + Number(b.views), 0);
  const prevReels = rows.reduce((s, b) => s + (b.prev_reels ?? 0), 0);
  const prevSpikes = rows.reduce((s, b) => s + (b.prev_spikes ?? 0), 0);
  const medians = rows.map((b) => b.median_views).filter((v): v is number => v !== null).sort((a, b) => a - b);
  return {
    reels,
    spikes,
    viral,
    views,
    share: reels ? spikes / reels : null,
    prevShare: prevReels ? prevSpikes / prevReels : null,
    median: medians.length ? medians[Math.floor(medians.length / 2)] : null,
  };
}

export default function OverviewPage() {
  const [daysS, setDays] = useParam("days", "30");
  const days = Number(daysS);
  const ov = useQuery({ queryKey: ["overview", days], queryFn: () => api.get<Overview>(`/overview?days=${days}`) });
  const top = useQuery({
    queryKey: ["anomalies", "top", days],
    queryFn: () => api.get<{ items: MediaRow[] }>(`/anomalies?days=${days}&scope=competitors&min_category=strong&limit=8`),
  });

  const brands = ov.data?.brands ?? [];
  const slot = useMemo(() => new Map([...brands].sort((a, b) => a.id - b.id).map((b, i) => [b.id, i])), [brands]);
  const own = aggregate(brands.filter((b) => b.is_own));
  const comp = aggregate(brands.filter((b) => !b.is_own));

  const chartOption = useCallback(() => {
    const weekly = ov.data?.weekly ?? [];
    const weeks = [...new Set(weekly.map((w) => w.week))].sort();
    const base = chartChrome();
    return {
      ...base,
      tooltip: { ...(base.tooltip as object), trigger: "axis", valueFormatter: (v: unknown) => (v === null || v === undefined ? "нет роликов" : `${Number(v).toFixed(1)}%`) },
      xAxis: { ...(base.xAxis as object), type: "category", data: weeks.map((w) => new Date(w).toLocaleDateString("ru-RU", { day: "numeric", month: "short" })) },
      yAxis: { ...(base.yAxis as object), type: "value", axisLabel: { formatter: "{value}%", color: cssVar("--muted") } },
      series: brands
        .slice()
        .sort((a, b) => a.id - b.id)
        .slice(0, 8)
        .map((b) => {
          const byWeek = new Map(weekly.filter((w) => w.brand_id === b.id).map((w) => [w.week, w]));
          return {
            name: b.name,
            type: "line",
            smooth: false,
            symbolSize: 8,
            connectNulls: false,
            lineStyle: { width: b.is_own ? 3 : 2 },
            color: seriesColor(slot.get(b.id) ?? 0),
            data: weeks.map((w) => {
              const r = byWeek.get(w);
              return r && r.reels > 0 ? +((r.spikes / r.reels) * 100).toFixed(2) : null;
            }),
          };
        }),
    } as EChartsOption;
  }, [ov.data, brands, slot]);

  return (
    <div className="stack" style={{ gap: 20 }}>
      <div className="head">
        <div>
          <h1>Обзор</h1>
          <div className="sub">Наш бренд и наши креаторы против конкурентов: сколько роликов «залетает» и насколько</div>
        </div>
        <PeriodPicker value={days} onChange={(d) => setDays(String(d))} />
      </div>

      {ov.isLoading && <Loading h={120} />}
      {ov.error && <ErrorBox error={ov.error} />}
      {ov.data && brands.length === 0 && (
        <Empty>
          Брендов пока нет. <Link to="/brands">Добавьте бренды и креаторов</Link> — парсер начнёт сбор.
        </Empty>
      )}

      {ov.data && brands.length > 0 && (
        <>
          <div className="grid-kpi">
            <KpiTile
              label="Доля всплесков — мы"
              value={fmtPct(own.share)}
              delta={<Delta cur={own.share} prev={own.prevShare} kind="pp" />}
              hint="Ролики с всплеском ×2 и выше / все ролики наших креаторов за период"
            />
            <KpiTile
              label="Доля всплесков — конкуренты"
              value={fmtPct(comp.share)}
              delta={<Delta cur={comp.share} prev={comp.prevShare} kind="pp" />}
            />
            <KpiTile label="Вирусных (×10+) — мы / конкуренты" value={`${own.viral} / ${comp.viral}`} delta={<span className="muted">из {fmtInt(own.reels)} / {fmtInt(comp.reels)} роликов</span>} />
            <KpiTile label="Медиана просмотров ролика — мы" value={fmtCompact(own.median)} delta={<span className="muted">у конкурентов {fmtCompact(comp.median)}</span>} />
          </div>

          <div className="card flush">
            <div className="card-head">
              <h2>Сравнение брендов</h2>
              <span className="hint">ролики креаторов бренда, без официального аккаунта</span>
            </div>
            <SortTable<BrandStats>
              rows={brands}
              rowKey={(b) => b.id}
              initial="share"
              columns={[
                {
                  key: "name",
                  label: "Бренд",
                  sort: (b) => b.name,
                  render: (b) => (
                    <span className="row" style={{ gap: 8, flexWrap: "nowrap", whiteSpace: "nowrap" }}>
                      <span className="dot" style={{ width: 10, height: 10, borderRadius: 3, background: seriesColor(slot.get(b.id) ?? 0), display: "inline-block" }} />
                      <Link to={`/brands/${b.id}`} style={{ fontWeight: 600 }}>{b.name}</Link>
                      {b.is_own && <span className="tag own">наш</span>}
                    </span>
                  ),
                },
                { key: "creators", label: "Креаторов", right: true, sort: (b) => b.creators, render: (b) => <>{b.active_creators}<span className="muted"> / {b.creators}</span></>, title: "публиковали за период / всего отслеживается" },
                { key: "reels", label: "Роликов", right: true, sort: (b) => b.reels, render: (b) => fmtInt(b.reels) },
                { key: "views", label: "Просмотры", right: true, sort: (b) => Number(b.views), render: (b) => fmtCompact(b.views) },
                { key: "median", label: "Медиана ролика", right: true, sort: (b) => b.median_views, render: (b) => fmtCompact(b.median_views) },
                { key: "spikes", label: "Всплесков", right: true, sort: (b) => b.spikes, render: (b) => fmtInt(b.spikes) },
                { key: "viral", label: "Viral", right: true, sort: (b) => b.viral, render: (b) => fmtInt(b.viral) },
                {
                  key: "share",
                  label: "Доля всплесков",
                  right: true,
                  sort: (b) => b.spike_share,
                  render: (b) => (
                    <span>
                      {fmtPct(b.spike_share)}{" "}
                      {b.spike_share !== null && b.prev_spike_share !== null && (
                        <span className={b.spike_share >= b.prev_spike_share ? "up small" : "down small"}>
                          {b.spike_share >= b.prev_spike_share ? "▲" : "▼"}
                        </span>
                      )}
                    </span>
                  ),
                },
                { key: "cand", label: "Кандидаты", right: true, sort: (b) => b.candidates, render: (b) => (b.candidates ? <Link to={`/candidates?brand=${b.id}`}>{b.candidates}</Link> : <span className="muted">0</span>) },
              ]}
            />
          </div>

          <div className="card">
            <h2>Доля всплесков по неделям</h2>
            <Chart option={chartOption} height={300} />
            <div className="hint">Пропуск на линии — у бренда не было роликов на этой неделе.</div>
          </div>
        </>
      )}

      <div className="card">
        <div className="row" style={{ justifyContent: "space-between", marginBottom: 12 }}>
          <h2 style={{ margin: 0 }}>Самые сильные всплески конкурентов</h2>
          <Link to={`/anomalies?days=${days}&scope=competitors`}>Все аномалии →</Link>
        </div>
        {top.isLoading && <Loading />}
        {top.error && <ErrorBox error={top.error} />}
        {top.data && top.data.items.length === 0 && <Empty>За период нет всплесков ×5 и выше.</Empty>}
        {top.data && top.data.items.length > 0 && (
          <div className="media-grid">
            {top.data.items.map((m) => (
              <MediaCard key={m.media_pk} m={m} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

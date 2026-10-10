import { useQuery } from "@tanstack/react-query";
import { useCallback } from "react";
import { api, type Brand, type InsightRow, type Insights } from "../api";
import { Chart, barOption, cssVar } from "../components/Chart";
import { Empty, ErrorBox, KpiTile, Loading, SortTable, downloadCsv, useParam, type Column } from "../components/ui";
import { fmtCompact, fmtInt, fmtPct, fmtRatio } from "../format";

const PERIODS = [
  { days: 30, label: "30 дней" },
  { days: 90, label: "90 дней" },
  { days: 180, label: "полгода" },
  { days: 365, label: "год" },
];
const WEEKDAYS = ["", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
const r = (v: unknown) => (v === null || v === undefined ? null : Number(v));

function tooltip(row: InsightRow, title: string): string {
  return [
    `<b>${title}</b>`,
    `обычно ${fmtRatio(r(row.median_ratio), 2)} от уровня автора`,
    `всплесков: ${fmtPct(r(row.spike_rate))} (${row.spikes} из ${row.reels})`,
    `медиана просмотров: ${fmtCompact(row.median_views)}`,
    `креаторов: ${row.creators}`,
  ].join("<br/>");
}

function RatioBars({ rows, label, height = 240, minReels = 5 }: { rows: InsightRow[]; label: (row: InsightRow) => string; height?: number; minReels?: number }) {
  const option = useCallback(
    () =>
      barOption(
        rows.map(label),
        rows.map((x) => (x.reels >= minReels ? r(x.median_ratio) : null)),
        {
          fmt: (v) => `×${v.toLocaleString("ru-RU", { maximumFractionDigits: 2 })}`,
          reference: 1,
          tooltip: (i) => (rows[i].reels >= minReels ? tooltip(rows[i], label(rows[i])) : `${label(rows[i])}: мало роликов (${rows[i].reels})`),
          highlight: (v) => v >= 1,
          color: cssVar("--series-1"),
        },
      ),
    [rows, label, minReels],
  );
  return <Chart option={option} height={height} />;
}

function Verdict({ rows, label }: { rows: InsightRow[]; label: (row: InsightRow) => string }) {
  const ok = rows.filter((x) => x.reels >= 10 && r(x.median_ratio) !== null);
  if (ok.length < 2) return null;
  const best = ok.reduce((a, b) => ((r(a.median_ratio) ?? 0) >= (r(b.median_ratio) ?? 0) ? a : b));
  const worst = ok.reduce((a, b) => ((r(a.median_ratio) ?? 9) <= (r(b.median_ratio) ?? 9) ? a : b));
  return (
    <div className="small ink2">
      Лучше всего: <b>{label(best)}</b> — {fmtRatio(r(best.median_ratio), 2)}, хуже всего: <b>{label(worst)}</b> — {fmtRatio(r(worst.median_ratio), 2)}
    </div>
  );
}

const groupCols = (first: string): Column<InsightRow>[] => [
  { key: "key", label: first, sort: (x) => String(x.key), csv: (x) => x.key, render: (x) => <b style={{ whiteSpace: "nowrap" }}>{x.key}</b> },
  { key: "reels", label: "Роликов", right: true, sort: (x) => x.reels, csv: (x) => x.reels, render: (x) => fmtInt(x.reels) },
  { key: "creators", label: "Креаторов", right: true, sort: (x) => x.creators, csv: (x) => x.creators, render: (x) => fmtInt(x.creators) },
  { key: "ratio", label: "Обычно от уровня автора", right: true, title: "медиана: просмотры ролика / медиана 20 предыдущих роликов автора", sort: (x) => r(x.median_ratio), csv: (x) => x.median_ratio, render: (x) => <span className={(r(x.median_ratio) ?? 1) >= 1 ? "up" : "down"}>{fmtRatio(r(x.median_ratio), 2)}</span> },
  { key: "rate", label: "Доля всплесков", right: true, sort: (x) => r(x.spike_rate), csv: (x) => x.spike_rate, render: (x) => fmtPct(r(x.spike_rate)) },
  { key: "views", label: "Медиана просмотров", right: true, sort: (x) => x.median_views, csv: (x) => x.median_views, render: (x) => fmtCompact(x.median_views) },
  { key: "er", label: "ER", right: true, sort: (x) => x.median_er, csv: (x) => x.median_er, render: (x) => fmtPct(x.median_er, 2) },
];

const PAIRS: [string, string, string][] = [
  ["Трендовый звук вместо своего", "Трендовый / лицензионный звук", "Свой звук"],
  ["Платное партнёрство", "Платное партнёрство", "Без пометки партнёрства"],
  ["Collab с соавторами", "Collab (соавторы)", "Без соавторов"],
  ["Геометка", "С геометкой", "Без геометки"],
  ["Отметки аккаунтов", "С отметками аккаунтов", "Без отметок"],
  ["Артикул WB в подписи", "С артикулом WB", "Без артикула"],
];

interface Pair {
  name: string;
  yes: InsightRow;
  no: InsightRow;
  effect: number | null;
}

function pairs(features: InsightRow[]): Pair[] {
  const by = new Map(features.map((f) => [String(f.key), f]));
  return PAIRS.flatMap(([name, a, b]) => {
    const yes = by.get(a);
    const no = by.get(b);
    if (!yes || !no) return [];
    const ya = r(yes.median_ratio);
    const na = r(no.median_ratio);
    return [{ name, yes, no, effect: ya !== null && na ? ya / na : null }];
  });
}

const pairCols: Column<Pair>[] = [
  { key: "name", label: "Приём", sort: (p) => p.name, csv: (p) => p.name, render: (p) => <b style={{ whiteSpace: "nowrap" }}>{p.name}</b> },
  { key: "n", label: "Роликов с / без", right: true, sort: (p) => p.yes.reels, csv: (p) => `${p.yes.reels} / ${p.no.reels}`, render: (p) => `${fmtInt(p.yes.reels)} / ${fmtInt(p.no.reels)}` },
  { key: "yes", label: "С приёмом", right: true, title: "медиана: просмотры / обычный уровень автора", sort: (p) => r(p.yes.median_ratio), csv: (p) => p.yes.median_ratio, render: (p) => fmtRatio(r(p.yes.median_ratio), 2) },
  { key: "no", label: "Без него", right: true, sort: (p) => r(p.no.median_ratio), csv: (p) => p.no.median_ratio, render: (p) => fmtRatio(r(p.no.median_ratio), 2) },
  { key: "rate", label: "Доля всплесков с / без", right: true, sort: (p) => r(p.yes.spike_rate), csv: (p) => `${p.yes.spike_rate} / ${p.no.spike_rate}`, render: (p) => `${fmtPct(r(p.yes.spike_rate))} / ${fmtPct(r(p.no.spike_rate))}` },
  {
    key: "effect",
    label: "Эффект",
    right: true,
    title: "во сколько раз ролики с приёмом набирают больше, чем без него (относительно уровня автора)",
    sort: (p) => p.effect,
    csv: (p) => p.effect,
    render: (p) =>
      p.effect === null ? "—" : (
        <b className={p.effect >= 1.02 ? "up" : p.effect <= 0.98 ? "down" : "muted"}>
          {p.effect >= 1.02 ? "▲ +" : p.effect <= 0.98 ? "▼ " : ""}
          {Math.round((p.effect - 1) * 100)}%
        </b>
      ),
  },
];

export default function InsightsPage() {
  const [days, setDays] = useParam("days", "180");
  const [scope, setScope] = useParam("scope", "all");
  const [brandsParam, setBrands] = useParam("brands", "");
  const selected = brandsParam ? brandsParam.split(",").map(Number) : [];
  const brands = useQuery({ queryKey: ["brands"], queryFn: () => api.get<Brand[]>("/brands") });
  const qs = new URLSearchParams({ days, scope });
  selected.forEach((id) => qs.append("brand_id", String(id)));
  const q = useQuery({ queryKey: ["insights", qs.toString()], queryFn: () => api.get<Insights>(`/insights?${qs}`) });
  const d = q.data;

  const toggleBrand = (id: number) => {
    const next = selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id];
    setBrands(next.length ? next.join(",") : null);
  };
  const base = d ? r(d.total.spike_rate) ?? 0 : 0;

  const tagCols: Column<InsightRow>[] = [
    { key: "key", label: "Хэштег", sort: (x) => String(x.key), csv: (x) => x.key, render: (x) => <b>#{x.key}</b> },
    { key: "reels", label: "Роликов", right: true, sort: (x) => x.reels, csv: (x) => x.reels, render: (x) => fmtInt(x.reels) },
    { key: "creators", label: "Креаторов", right: true, sort: (x) => x.creators, csv: (x) => x.creators, render: (x) => fmtInt(x.creators) },
    { key: "rate", label: "Доля всплесков", right: true, sort: (x) => r(x.spike_rate), csv: (x) => x.spike_rate, render: (x) => fmtPct(r(x.spike_rate)) },
    {
      key: "lift",
      label: "Лифт",
      title: "доля всплесков с хэштегом / доля всплесков в целом",
      sort: (x) => x.lift ?? null,
      csv: (x) => x.lift,
      render: (x) => {
        const l = x.lift ?? 0;
        return (
          <span style={{ whiteSpace: "nowrap" }}>
            <span className={`lift${l < 1 ? " neg" : ""}`} style={{ width: Math.min(120, l * 40) }} />
            {fmtRatio(l)}
          </span>
        );
      },
    },
    { key: "wilson", label: "Надёжность", right: true, title: "нижняя граница 95% интервала Уилсона для доли всплесков: учитывает размер выборки", sort: (x) => x.wilson_low ?? null, csv: (x) => x.wilson_low, render: (x) => fmtPct(x.wilson_low ?? null) },
    { key: "ratio", label: "Обычно от уровня автора", right: true, sort: (x) => r(x.median_ratio), csv: (x) => x.median_ratio, render: (x) => fmtRatio(r(x.median_ratio), 2) },
    { key: "views", label: "Медиана просмотров", right: true, sort: (x) => x.median_views, csv: (x) => x.median_views, render: (x) => fmtCompact(x.median_views) },
  ];

  return (
    <div className="stack" style={{ gap: 20 }}>
      <div className="head">
        <div>
          <h1>Что работает</h1>
          <div className="sub">
            Какие решения дают ролику больше просмотров. Сравнение идёт с обычным уровнем автора (медиана его 20 предыдущих Reels), поэтому крупные и маленькие креаторы сравнимы: ×1,0 — как обычно, ×1,3 — на 30% лучше.
          </div>
        </div>
      </div>

      <div className="card stack" style={{ gap: 12 }}>
        <div className="row" style={{ gap: 12 }}>
          <div className="seg">
            {PERIODS.map((p) => (
              <button key={p.days} className={Number(days) === p.days ? "on" : ""} onClick={() => setDays(String(p.days))}>{p.label}</button>
            ))}
          </div>
          <div className="seg">
            {[["all", "Все"], ["competitors", "Конкуренты"], ["own", "Наш бренд"]].map(([v, l]) => (
              <button key={v} className={scope === v ? "on" : ""} onClick={() => setScope(v)}>{l}</button>
            ))}
          </div>
        </div>
        {brands.data && (
          <div className="row" style={{ gap: 6 }}>
            <span className="hint">Бренды:</span>
            {brands.data.map((b) => (
              <button key={b.id} className={`chip${selected.includes(b.id) ? " on" : ""}`} onClick={() => toggleBrand(b.id)}>{b.name}</button>
            ))}
            {selected.length > 0 && <button className="ghost small" onClick={() => setBrands(null)}>сбросить</button>}
          </div>
        )}
      </div>

      {q.isLoading && <Loading h={400} />}
      {q.error && <ErrorBox error={q.error} />}
      {d && d.total.reels === 0 && <Empty>За период нет роликов под эти фильтры.</Empty>}
      {d && d.total.reels > 0 && (
        <>
          <div className="grid-kpi dense">
            <KpiTile label="Роликов в выборке" value={fmtInt(d.total.reels)} delta={<span className="muted">{d.total.creators} креаторов</span>} />
            <KpiTile label="Доля всплесков (×2+)" value={fmtPct(base)} delta={<span className="muted">{d.total.spikes} роликов</span>} />
            <KpiTile label="Медиана просмотров" value={fmtCompact(d.total.median_views)} />
            <KpiTile label="Средний ролик от уровня автора" value={fmtRatio(r(d.total.avg_ratio))} delta={<span className="muted">медиана {fmtRatio(r(d.total.median_ratio))}</span>} />
            <KpiTile label="ER (медиана)" value={fmtPct(d.total.median_er, 2)} />
          </div>

          <div className="grid2">
            <div className="card">
              <h2>Время публикации (МСК)</h2>
              <RatioBars rows={d.by_hour} label={(x) => `${x.key}:00`} />
              <Verdict rows={d.by_hour} label={(x) => `${x.key}:00`} />
            </div>
            <div className="card">
              <h2>День недели</h2>
              <RatioBars rows={d.by_weekday} label={(x) => WEEKDAYS[Number(x.key)] ?? String(x.key)} />
              <Verdict rows={d.by_weekday} label={(x) => WEEKDAYS[Number(x.key)] ?? String(x.key)} />
            </div>
            <div className="card">
              <h2>Длительность ролика</h2>
              <RatioBars rows={d.by_duration} label={(x) => String(x.key)} />
              <Verdict rows={d.by_duration} label={(x) => String(x.key)} />
            </div>
            <div className="card">
              <h2>Длина подписи</h2>
              <RatioBars rows={d.caption_length} label={(x) => String(x.key).replace(/^\d — /, "")} />
              <Verdict rows={d.caption_length} label={(x) => String(x.key).replace(/^\d — /, "")} />
            </div>
          </div>
          <div className="hint">Синие столбцы — лучше обычного уровня автора, серые — хуже. Пунктир — ×1,0. Наведите на столбец — число роликов и доля всплесков; группы меньше 5 роликов не показываются.</div>

          <div className="card flush">
            <div className="card-head">
              <h2>Приёмы: с ним и без него</h2>
              <button onClick={() => downloadCsv("features.csv", pairs(d.features), pairCols)}>CSV</button>
            </div>
            <SortTable<Pair> rows={pairs(d.features)} rowKey={(p) => p.name} columns={pairCols} initial="effect" />
            <div className="hint" style={{ padding: "8px 16px 12px" }}>
              Эффект — насколько ролики с приёмом лучше или хуже роликов без него, если сравнивать каждый с обычным уровнем его автора. Это корреляция, а не доказанная причина.
            </div>
          </div>

          <div className="card flush">
            <div className="card-head">
              <h2>Хэштеги</h2>
              <div className="row">
                <span className="hint">лифт &gt; 1 — с этим хэштегом всплески случаются чаще среднего; сортировка по надёжности учитывает число роликов</span>
                <button onClick={() => downloadCsv("hashtags.csv", d.hashtags, tagCols)}>CSV</button>
              </div>
            </div>
            {d.hashtags.length ? <SortTable<InsightRow> rows={d.hashtags} rowKey={(x) => String(x.key)} columns={tagCols} limit={40} /> : <Empty>Нет хэштегов с 5+ роликами.</Empty>}
          </div>

          <div className="grid2">
            <div className="card flush">
              <div className="card-head"><h2>Трендовые звуки</h2><span className="hint">использованы 2+ раза</span></div>
              {d.audio.length ? <SortTable<InsightRow> rows={d.audio} rowKey={(x) => String(x.key)} columns={groupCols("Звук")} /> : <Empty>Нет повторяющихся трендовых звуков.</Empty>}
            </div>
            <div className="card flush">
              <div className="card-head"><h2>Геометки</h2></div>
              {d.locations.length ? <SortTable<InsightRow> rows={d.locations} rowKey={(x) => String(x.key)} columns={groupCols("Место")} /> : <Empty>Роликов с геометкой нет.</Empty>}
            </div>
          </div>

          <div className="card">
            <h2>Распределение роликов по отношению к уровню автора</h2>
            <Chart
              option={() =>
                barOption(
                  d.ratio_histogram.map((x) => x.key),
                  d.ratio_histogram.map((x) => x.reels),
                  { fmt: (v) => fmtInt(v), highlight: () => true, color: cssVar("--series-1") },
                )
              }
              height={220}
            />
            <div className="hint">Большинство роликов набирает около обычного уровня автора; всплески — правый хвост (×2 и выше).</div>
          </div>
        </>
      )}
    </div>
  );
}

import { useQuery } from "@tanstack/react-query";
import { useCallback, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api, type BrandPeriod, type Leader, type MediaRow, type OverviewBrand, type OverviewV2 } from "../api";
import { Chart, lineOption, seriesColor } from "../components/Chart";
import { Empty, ErrorBox, Loading, MediaCard, PeriodPicker, SortTable, downloadCsv, useParam, type Column } from "../components/ui";
import { fmtCompact, fmtDec, fmtInt, fmtPct, fmtRatio } from "../format";

type Agg = {
  reels: number;
  activeCreators: number;
  gained: number;
  views: number;
  spikes: number;
  viral: number;
  million: number;
  avgViews: number | null;
  medianViews: number | null;
  share: number | null;
  er: number | null;
  likes: number;
};

const n = (v: unknown): number => (v === null || v === undefined ? 0 : Number(v));

function middle(xs: number[]): number | null {
  const s = [...xs].sort((a, b) => a - b);
  return s.length ? s[Math.floor(s.length / 2)] : null;
}

function aggregate(rows: OverviewBrand[], key: "cur" | "prev"): Agg {
  const ps = rows.map((b) => b[key]).filter((p): p is BrandPeriod => !!p);
  const reels = ps.reduce((s, p) => s + n(p.reels), 0);
  const spikes = ps.reduce((s, p) => s + n(p.spikes), 0);
  const views = ps.reduce((s, p) => s + n(p.views), 0);
  return {
    reels,
    activeCreators: ps.reduce((s, p) => s + n(p.active_creators), 0),
    gained: ps.reduce((s, p) => s + n(p.views_gained), 0),
    views,
    spikes,
    viral: ps.reduce((s, p) => s + n(p.viral), 0),
    million: ps.reduce((s, p) => s + n(p.million_plus), 0),
    avgViews: reels ? views / reels : null,
    medianViews: middle(ps.map((p) => p.median_views).filter((v): v is number => v !== null)),
    share: reels ? spikes / reels : null,
    er: middle(ps.map((p) => p.er_median).filter((v): v is number => v !== null)),
    likes: ps.reduce((s, p) => s + n(p.likes), 0),
  };
}

function Change({ cur, prev, pp = false }: { cur: number | null; prev: number | null; pp?: boolean }) {
  if (cur === null || prev === null || (!pp && prev === 0)) return <span className="muted">—</span>;
  const d = pp ? (cur - prev) * 100 : (cur / prev - 1) * 100;
  if (Math.abs(d) < 0.05) return <span className="muted">0</span>;
  return (
    <span className={d > 0 ? "up" : "down"}>
      {d > 0 ? "▲ +" : "▼ "}
      {d.toLocaleString("ru-RU", { maximumFractionDigits: pp ? 1 : 0 })}
      {pp ? " п.п." : "%"}
    </span>
  );
}

function CompareTile(props: { label: string; own: number | null; comp: number | null; ownPrev: number | null; hint?: string; fmt: (v: number | null) => string; pp?: boolean }) {
  const { label, own, comp, ownPrev, hint, fmt, pp } = props;
  return (
    <div className="card kpi" title={hint}>
      <div className="label">{label}</div>
      <div className="value">{fmt(own)}</div>
      <div className="delta"><Change cur={own} prev={ownPrev} pp={pp} /> <span className="muted">к прошлому периоду</span></div>
      <div className="delta muted">конкуренты: <b className="ink2">{fmt(comp)}</b></div>
    </div>
  );
}

const METRICS = [
  { key: "views", label: "Просмотры в день" },
  { key: "reels", label: "Роликов в неделю" },
  { key: "share", label: "Доля всплесков" },
  { key: "median", label: "Медиана ролика" },
] as const;

const fmtSmall = (v: number | null) => (v === null ? "—" : v.toLocaleString("ru-RU", { maximumFractionDigits: 1 }));

export default function OverviewPage() {
  const [daysS, setDays] = useParam("days", "30");
  const days = Number(daysS);
  const [metric, setMetric] = useState<(typeof METRICS)[number]["key"]>("views");
  const ov = useQuery({ queryKey: ["overview", days], queryFn: () => api.get<OverviewV2>(`/overview?days=${days}`) });
  const top = useQuery({
    queryKey: ["anomalies", "top", days],
    queryFn: () => api.get<{ items: MediaRow[] }>(`/anomalies?days=${days}&scope=competitors&min_category=strong&limit=8`),
  });

  const brands = useMemo(() => ov.data?.brands ?? [], [ov.data]);
  const slot = useMemo(() => new Map([...brands].sort((a, b) => a.id - b.id).map((b, i) => [b.id, i])), [brands]);
  const own = brands.filter((b) => b.is_own);
  const comp = brands.filter((b) => !b.is_own);
  const ownCur = aggregate(own, "cur");
  const ownPrev = aggregate(own, "prev");
  const compCur = aggregate(comp, "cur");
  // прошлый период целиком до начала наблюдения: его прирост просмотров неизвестен
  const prevObserved =
    !!ov.data?.observed_since && new Date(ov.data.observed_since).getTime() <= Date.now() - 2 * days * 86_400_000 + 86_400_000;
  // суммы конкурентов — в среднем на бренд, чтобы сравнение не зависело от их числа
  const perBrand = (v: number | null) => (v === null || !comp.length ? null : v / comp.length);

  const chartOption = useCallback(() => {
    const data = ov.data;
    if (!data) return {};
    const ordered = [...brands].sort((a, b) => a.id - b.id).slice(0, 8);
    const color = (id: number) => seriesColor(slot.get(id) ?? 0);
    const label = (d: string) => new Date(d).toLocaleDateString("ru-RU", { day: "numeric", month: "short" });
    if (metric === "views") {
      const dates = [...new Set(data.daily.map((d) => d.date))].sort();
      return lineOption(
        dates.map(label),
        ordered.map((b) => {
          const m = new Map(data.daily.filter((d) => d.brand_id === b.id).map((d) => [d.date, Number(d.views)]));
          return { name: b.name, color: color(b.id), width: b.is_own ? 3 : 2, data: dates.map((d) => m.get(d) ?? null) };
        }),
        (v) => fmtCompact(v),
      );
    }
    const weeks = [...new Set(data.weekly.map((w) => w.week))].sort();
    const pick = (w: { reels: number; spikes: number; median_views: number | null }) =>
      metric === "reels" ? w.reels : metric === "share" ? (w.reels ? (w.spikes / w.reels) * 100 : null) : w.median_views;
    return lineOption(
      weeks.map(label),
      ordered.map((b) => {
        const m = new Map(data.weekly.filter((w) => w.brand_id === b.id).map((w) => [w.week, w]));
        return { name: b.name, color: color(b.id), width: b.is_own ? 3 : 2, data: weeks.map((w) => (m.has(w) ? pick(m.get(w)!) : null)) };
      }),
      (v) => (metric === "share" ? `${v.toFixed(0)}%` : metric === "reels" ? fmtInt(v) : fmtCompact(v)),
    );
  }, [ov.data, brands, slot, metric]);

  const share = (p: BrandPeriod | null) => (p?.reels ? n(p.spikes) / p.reels : null);
  const brandColumns: Column<OverviewBrand>[] = [
    {
      key: "name",
      label: "Бренд",
      sort: (b) => b.name,
      csv: (b) => b.name,
      render: (b) => (
        <span className="row" style={{ gap: 8, flexWrap: "nowrap" }}>
          <span style={{ width: 10, height: 10, borderRadius: 3, background: seriesColor(slot.get(b.id) ?? 0), display: "inline-block", flex: "none" }} />
          <Link to={`/brands/${b.id}`} style={{ fontWeight: 600 }}>{b.name}</Link>
          {b.is_own && <span className="tag own">наш</span>}
        </span>
      ),
    },
    { key: "creators", label: "Креаторов", right: true, title: "публиковали за период / отслеживается", sort: (b) => b.creators, csv: (b) => b.creators, render: (b) => <>{fmtInt(b.cur?.active_creators ?? 0)}<span className="muted"> / {b.creators}</span></> },
    { key: "reels", label: "Роликов", right: true, sort: (b) => n(b.cur?.reels), csv: (b) => b.cur?.reels, render: (b) => <>{fmtInt(b.cur?.reels ?? 0)} <span className="small"><Change cur={n(b.cur?.reels)} prev={b.prev ? n(b.prev.reels) : null} /></span></> },
    { key: "per", label: "На креатора", right: true, title: "роликов на активного креатора", sort: (b) => (b.cur?.active_creators ? n(b.cur.reels) / b.cur.active_creators : null), csv: (b) => (b.cur?.active_creators ? fmtDec(n(b.cur.reels) / b.cur.active_creators) : ""), render: (b) => (b.cur?.active_creators ? fmtDec(n(b.cur.reels) / b.cur.active_creators) : "—") },
    { key: "gained", label: "Просмотры за период", right: true, title: "прирост просмотров всех роликов бренда за даты периода", sort: (b) => n(b.cur?.views_gained), csv: (b) => b.cur?.views_gained, render: (b) => <>{fmtCompact(b.cur?.views_gained)} <span className="small"><Change cur={n(b.cur?.views_gained)} prev={b.prev && prevObserved ? n(b.prev.views_gained) : null} /></span></> },
    { key: "avg", label: "Среднее", right: true, title: "средние просмотры ролика, опубликованного за период", sort: (b) => b.cur?.avg_views ?? null, csv: (b) => b.cur?.avg_views, render: (b) => fmtCompact(b.cur?.avg_views) },
    { key: "median", label: "Медиана", right: true, sort: (b) => b.cur?.median_views ?? null, csv: (b) => b.cur?.median_views, render: (b) => <>{fmtCompact(b.cur?.median_views)} <span className="small"><Change cur={b.cur?.median_views ?? null} prev={b.prev?.median_views ?? null} /></span></> },
    { key: "p90", label: "P90", right: true, title: "90% роликов набрали меньше", sort: (b) => b.cur?.p90_views ?? null, csv: (b) => b.cur?.p90_views, render: (b) => fmtCompact(b.cur?.p90_views) },
    { key: "max", label: "Максимум", right: true, sort: (b) => b.cur?.max_views ?? null, csv: (b) => b.cur?.max_views, render: (b) => fmtCompact(b.cur?.max_views) },
    { key: "spikes", label: "Всплесков", right: true, sort: (b) => n(b.cur?.spikes), csv: (b) => b.cur?.spikes, render: (b) => fmtInt(b.cur?.spikes ?? 0) },
    { key: "share", label: "Доля всплесков", right: true, sort: (b) => share(b.cur), csv: (b) => share(b.cur), render: (b) => <>{fmtPct(share(b.cur))} <span className="small"><Change cur={share(b.cur)} prev={share(b.prev)} pp /></span></> },
    { key: "viral", label: "Viral", right: true, sort: (b) => n(b.cur?.viral), csv: (b) => b.cur?.viral, render: (b) => fmtInt(b.cur?.viral ?? 0) },
    { key: "mil", label: "1 млн+", right: true, sort: (b) => n(b.cur?.million_plus), csv: (b) => b.cur?.million_plus, render: (b) => fmtInt(b.cur?.million_plus ?? 0) },
    { key: "ratio", label: "Медиана ×", right: true, title: "медиана отношения просмотров ролика к обычному уровню автора", sort: (b) => b.cur?.median_ratio ?? null, csv: (b) => b.cur?.median_ratio, render: (b) => fmtRatio(b.cur?.median_ratio) },
    { key: "er", label: "ER", right: true, title: "медиана (лайки + комментарии + репосты) / просмотры", sort: (b) => b.cur?.er_median ?? null, csv: (b) => b.cur?.er_median, render: (b) => fmtPct(b.cur?.er_median ?? null, 2) },
    { key: "likes", label: "Лайков", right: true, sort: (b) => n(b.cur?.likes), csv: (b) => b.cur?.likes, render: (b) => fmtCompact(b.cur?.likes) },
    { key: "comments", label: "Комментариев", right: true, sort: (b) => n(b.cur?.comments), csv: (b) => b.cur?.comments, render: (b) => fmtCompact(b.cur?.comments) },
    { key: "dur", label: "Длительность", right: true, sort: (b) => n(b.cur?.avg_duration_s), csv: (b) => b.cur?.avg_duration_s, render: (b) => (b.cur?.avg_duration_s ? `${Math.round(n(b.cur.avg_duration_s))} с` : "—") },
    { key: "paid", label: "Партнёрских", right: true, sort: (b) => n(b.cur?.paid_share), csv: (b) => b.cur?.paid_share, render: (b) => fmtPct(b.cur ? n(b.cur.paid_share) : null, 0) },
    { key: "audio", label: "Свой звук", right: true, sort: (b) => n(b.cur?.original_audio_share), csv: (b) => b.cur?.original_audio_share, render: (b) => fmtPct(b.cur ? n(b.cur.original_audio_share) : null, 0) },
    { key: "aud", label: "Аудитория креаторов", right: true, title: "сумма подписчиков отслеживаемых креаторов", sort: (b) => n(b.creators_followers), csv: (b) => b.creators_followers, render: (b) => fmtCompact(b.creators_followers) },
    { key: "shop", label: "Подписчики бренда", right: true, sort: (b) => b.shop_followers, csv: (b) => b.shop_followers, render: (b) => fmtCompact(b.shop_followers) },
    { key: "cand", label: "Кандидаты", right: true, sort: (b) => b.candidates, csv: (b) => b.candidates, render: (b) => (b.candidates ? <Link to={`/candidates?brand=${b.id}`}>{b.candidates}</Link> : <span className="muted">0</span>) },
  ];

  const leaders = ov.data?.leaders ?? [];
  const leaderColumns: Column<Leader>[] = [
    { key: "i", label: "#", render: (l) => <span className="muted num">{leaders.indexOf(l) + 1}</span> },
    { key: "user", label: "Креатор", sort: (l) => l.username, render: (l) => <Link to={`/accounts/${l.user_pk}`} style={{ fontWeight: 600 }}>@{l.username}</Link> },
    { key: "brand", label: "Бренд", sort: (l) => l.brand_name, render: (l) => <span className={`tag${l.is_own ? " own" : ""}`}>{l.brand_name}</span> },
    { key: "gained", label: "Просмотры за период", right: true, sort: (l) => l.views_gained, render: (l) => <b>{fmtCompact(l.views_gained)}</b> },
    { key: "reels", label: "Роликов", right: true, sort: (l) => l.reels, render: (l) => l.reels },
    { key: "avg", label: "Среднее", right: true, sort: (l) => l.avg_views, render: (l) => fmtCompact(l.avg_views) },
    { key: "median", label: "Медиана", right: true, sort: (l) => l.median_views, render: (l) => fmtCompact(l.median_views) },
    { key: "spikes", label: "Всплесков", right: true, sort: (l) => l.spikes, render: (l) => l.spikes },
    { key: "trend", label: "Тренд", right: true, title: "медиана 20 последних / 20 предыдущих", sort: (l) => n(l.trend), render: (l) => (l.trend === null ? "—" : <span className={n(l.trend) >= 1 ? "up" : "down"}>{n(l.trend) >= 1 ? "▲" : "▼"} {fmtRatio(l.trend, 2)}</span>) },
    { key: "followers", label: "Подписчики", right: true, sort: (l) => l.followers, render: (l) => fmtCompact(l.followers) },
  ];

  const tiles = [
    { label: "Просмотры за период", own: ownCur.gained, prev: prevObserved ? ownPrev.gained : null, comp: perBrand(compCur.gained), fmt: fmtCompact, hint: "прирост просмотров всех роликов за даты периода; у конкурентов — в среднем на бренд" },
    { label: "Опубликовано роликов", own: ownCur.reels, prev: ownPrev.reels, comp: perBrand(compCur.reels), fmt: fmtSmall },
    { label: "Активных креаторов", own: ownCur.activeCreators, prev: ownPrev.activeCreators, comp: perBrand(compCur.activeCreators), fmt: fmtSmall },
    { label: "Средние просмотры ролика", own: ownCur.avgViews, prev: ownPrev.avgViews, comp: compCur.avgViews, fmt: fmtCompact },
    { label: "Медиана ролика", own: ownCur.medianViews, prev: ownPrev.medianViews, comp: compCur.medianViews, fmt: fmtCompact },
    { label: "Доля всплесков (×2+)", own: ownCur.share, prev: ownPrev.share, comp: compCur.share, fmt: (v: number | null) => fmtPct(v), pp: true },
    { label: "Viral (×10+)", own: ownCur.viral, prev: ownPrev.viral, comp: perBrand(compCur.viral), fmt: fmtSmall },
    { label: "Роликов 1 млн+", own: ownCur.million, prev: ownPrev.million, comp: perBrand(compCur.million), fmt: fmtSmall },
    { label: "ER (медиана)", own: ownCur.er, prev: ownPrev.er, comp: compCur.er, fmt: (v: number | null) => fmtPct(v, 2), pp: true },
    { label: "Лайков", own: ownCur.likes, prev: ownPrev.likes, comp: perBrand(compCur.likes), fmt: fmtCompact },
  ];

  let body: ReactNode = null;
  if (ov.isLoading) body = <Loading h={300} />;
  else if (ov.error) body = <ErrorBox error={ov.error} />;
  else if (ov.data && brands.length === 0)
    body = <Empty>Брендов пока нет. <Link to="/brands">Добавьте бренды и креаторов</Link> — парсер начнёт сбор.</Empty>;
  else if (ov.data)
    body = (
      <>
        <section className="stack" style={{ gap: 10 }}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <h2 style={{ margin: 0 }}>{own.length ? `${own.map((b) => b.name).join(", ")} против конкурентов` : "Конкуренты"}</h2>
            <span className="hint">у конкурентов суммы — в среднем на бренд ({comp.length}), доли и медианы — по всем их роликам</span>
          </div>
          <div className="grid-kpi dense">
            {tiles.map((t) => (
              <CompareTile key={t.label} label={t.label} own={t.own} ownPrev={t.prev} comp={t.comp} fmt={t.fmt} hint={t.hint} pp={t.pp} />
            ))}
          </div>
        </section>

        <div className="card">
          <div className="row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
            <h2 style={{ margin: 0 }}>Динамика по брендам</h2>
            <div className="seg">
              {METRICS.map((m) => (
                <button key={m.key} className={metric === m.key ? "on" : ""} onClick={() => setMetric(m.key)}>{m.label}</button>
              ))}
            </div>
          </div>
          <Chart option={chartOption} height={320} />
          <div className="hint">
            {metric === "views"
              ? "Прирост просмотров по дням (сумма по роликам бренда). Просмотры, набранные до начала наблюдения, по дням не раскладываются."
              : "По неделям публикации. Разрыв линии — у бренда не было роликов на этой неделе."}
          </div>
        </div>

        <div className="card flush">
          <div className="card-head">
            <h2>Сравнение брендов — {days} дн.</h2>
            <div className="row">
              <span className="hint">ролики креаторов бренда, без официального аккаунта; ▲▼ — к прошлому периоду</span>
              <button onClick={() => downloadCsv(`brands_${days}d.csv`, brands, brandColumns)}>CSV</button>
            </div>
          </div>
          <SortTable<OverviewBrand> rows={brands} rowKey={(b) => b.id} initial="gained" columns={brandColumns} sticky />
        </div>

        <div className="card flush">
          <div className="card-head">
            <h2>Лидеры периода по просмотрам</h2>
            <Link to={`/creators?days=${days}`}>Все креаторы и показатели →</Link>
          </div>
          {leaders.length ? (
            <SortTable<Leader> rows={leaders} rowKey={(l) => `${l.user_pk}-${l.brand_id}`} columns={leaderColumns} />
          ) : (
            <Empty>За период нет публикаций.</Empty>
          )}
        </div>
      </>
    );

  return (
    <div className="stack" style={{ gap: 20 }}>
      <div className="head">
        <div>
          <h1>Обзор</h1>
          <div className="sub">Наш бренд и наши креаторы против конкурентов: сколько публикуют, сколько набирают и что «залетает»</div>
        </div>
        <PeriodPicker value={days} onChange={(d) => setDays(String(d))} />
      </div>
      {body}
      <div className="card">
        <div className="row" style={{ justifyContent: "space-between", marginBottom: 12 }}>
          <h2 style={{ margin: 0 }}>Самые сильные всплески конкурентов</h2>
          <Link to={`/anomalies?days=${days}&scope=competitors`}>Все аномалии →</Link>
        </div>
        {top.isLoading && <Loading />}
        {top.data && top.data.items.length === 0 && <Empty>За период нет всплесков ×5 и выше.</Empty>}
        {top.data && top.data.items.length > 0 && <div className="media-grid">{top.data.items.map((m) => <MediaCard key={m.media_pk} m={m} />)}</div>}
      </div>
    </div>
  );
}

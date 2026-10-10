import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { EChartsOption } from "echarts";
import { useCallback, useMemo } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type AccountDetail, type AccountSeries, type MediaRow, type Num } from "../api";
import { Chart, barOption, chartChrome, cssVar, lineOption } from "../components/Chart";
import { Empty, ErrorBox, KpiTile, Loading, MediaCard, toast, useParam } from "../components/ui";
import { CATEGORY_LABEL, LINK_LABEL, STATUS_LABEL, TASK_LABEL, fmtAgo, fmtCompact, fmtDate, fmtDateTime, fmtDec, fmtInt, fmtPct, fmtRatio } from "../format";

const num = (v: Num | undefined): number | null => (v === null || v === undefined ? null : Number(v));
const SORTS = { date: "сначала новые", views: "по просмотрам", ratio: "по силе всплеска", er: "по ER" } as const;

function Signed({ v, suffix = "" }: { v: number | null; suffix?: string }) {
  if (v === null) return <span className="muted">нет данных</span>;
  return <span className={v >= 0 ? "up" : "down"}>{v >= 0 ? "▲ +" : "▼ "}{fmtCompact(Math.abs(v))}{suffix}</span>;
}

const ORDER = ["none", "high", "strong", "viral"] as const;

function median(xs: number[]): number | null {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

export default function AccountPage() {
  const userPk = Number(useParams().userPk);
  const qc = useQueryClient();
  const [onlySpikes, setOnlySpikes] = useParam("spikes", "0");
  const q = useQuery({ queryKey: ["account", userPk], queryFn: () => api.get<AccountDetail>(`/accounts/${userPk}`) });
  const series = useQuery({ queryKey: ["account-series", userPk], queryFn: () => api.get<AccountSeries>(`/accounts/${userPk}/series?days=90`) });
  const [sort, setSort] = useParam("sort", "date");
  const st = series.data?.stats ?? null;
  const viewsOption = useCallback(() => {
    const rows = series.data?.views ?? [];
    return lineOption(
      rows.map((r) => new Date(r.date).toLocaleDateString("ru-RU", { day: "numeric", month: "short" })),
      [{ name: "Просмотры", color: cssVar("--series-1"), data: rows.map((r) => Number(r.views)) }],
      (v) => fmtCompact(v),
    );
  }, [series.data]);
  const followersOption = useCallback(() => {
    const rows = series.data?.followers ?? [];
    const opt = lineOption(
      rows.map((r) => new Date(r.date).toLocaleDateString("ru-RU", { day: "numeric", month: "short" })),
      [{ name: "Подписчики", color: cssVar("--series-3"), data: rows.map((r) => r.followers) }],
      // узкий диапазон: подписи в тысячах без округления до миллионов
      (v) => `${Math.round(v / 1000).toLocaleString("ru-RU")} тыс.`,
    );
    return { ...opt, yAxis: { ...(opt.yAxis as object), scale: true } };
  }, [series.data]);
  const hoursOption = useCallback(() => {
    const rows = series.data?.by_hour ?? [];
    const best = Math.max(...rows.map((r) => r.median_views ?? 0));
    return barOption(
      rows.map((r) => `${r.hour}:00`),
      rows.map((r) => r.median_views),
      {
        fmt: (v) => fmtCompact(v),
        tooltip: (i) => `<b>${rows[i].hour}:00</b><br/>роликов: ${rows[i].reels}<br/>медиана: ${fmtCompact(rows[i].median_views)}`,
        highlight: (v) => v >= best * 0.8,
        color: cssVar("--series-1"),
      },
    );
  }, [series.data]);
  const refresh = useMutation({
    mutationFn: () => api.post<{ queued: boolean }>(`/accounts/${userPk}/refresh`),
    onSuccess: (r) => {
      toast(r.queued ? "Ручное обновление поставлено первым в очередь" : "Обновление уже в очереди");
      qc.invalidateQueries({ queryKey: ["account", userPk] });
    },
  });

  const media = q.data?.media ?? [];
  const stats = useMemo(() => {
    const views = media.slice(0, 20).map((m) => m.views).filter((v): v is number => v !== null);
    const prev = media.slice(20, 40).map((m) => m.views).filter((v): v is number => v !== null);
    const spikes = media.filter((m) => m.spike_category && ["high", "strong", "viral"].includes(m.spike_category));
    const m20 = median(views);
    const p20 = median(prev);
    return { m20, trend: m20 && p20 ? m20 / p20 : null, spikes: spikes.length, hit: media.length ? spikes.length / media.length : null };
  }, [media]);

  const option = useCallback((): EChartsOption => {
    const base = chartChrome();
    const color: Record<string, string> = {
      none: cssVar("--muted"),
      high: cssVar("--spike-high") === "#5a3020" ? "#b9805f" : "#e8a07c",
      strong: cssVar("--spike-strong"),
      viral: cssVar("--spike-viral"),
    };
    return {
      ...base,
      tooltip: {
        ...(base.tooltip as object),
        trigger: "item",
        formatter: (p: unknown) => {
          const m = (p as { data: { m: MediaRow } }).data.m;
          return `<b>${fmtCompact(m.views)}</b> просмотров<br/>${new Date(m.taken_at).toLocaleDateString("ru-RU")}` +
            (m.spike_ratio !== null ? `<br/>${fmtRatio(m.spike_ratio)} к обычному (${fmtCompact(m.baseline_median)})` : "") +
            `<br/><span style="opacity:.7">${(m.caption ?? "").slice(0, 60)}</span>`;
        },
      },
      xAxis: { ...(base.xAxis as object), type: "time" },
      yAxis: { ...(base.yAxis as object), type: "log", axisLabel: { color: cssVar("--muted"), formatter: (v: number) => fmtCompact(v) } },
      series: ORDER.map((cat) => ({
        name: cat === "none" ? "без всплеска" : `${CATEGORY_LABEL[cat]} (${cat === "high" ? "×2–5" : cat === "strong" ? "×5–10" : "×10+"})`,
        type: "scatter",
        symbolSize: cat === "none" ? 8 : 11,
        itemStyle: { color: color[cat], borderColor: cssVar("--surface"), borderWidth: 2 },
        data: media
          .filter((m) => m.views && (m.spike_category === cat || (cat === "none" && !["high", "strong", "viral"].includes(m.spike_category ?? ""))))
          .map((m) => ({ value: [m.taken_at, m.views], m })),
      })),
    };
  }, [media]);

  if (q.isLoading) return <Loading h={400} />;
  if (q.error) return <ErrorBox error={q.error} />;
  if (!q.data) return null;
  const { account: a, snapshot, brands, tasks } = q.data;
  const filtered = onlySpikes === "1" ? media.filter((m) => ["high", "strong", "viral"].includes(m.spike_category ?? "")) : media;
  const key = (m: MediaRow): number =>
    sort === "views" ? num(m.views) ?? -1 : sort === "ratio" ? num(m.spike_ratio) ?? -1 : sort === "er" ? num(m.er) ?? -1 : new Date(m.taken_at).getTime();
  const shown = [...filtered].sort((a, b) => key(b) - key(a));

  return (
    <div className="stack" style={{ gap: 20 }}>
      <div className="head">
        <div>
          <h1 className="row" style={{ gap: 10 }}>
            @{a.username}
            {a.status !== "active" && <span className="tag crit">{a.status}</span>}
            {a.is_verified && <span className="tag">verified</span>}
          </h1>
          <div className="sub">
            {a.full_name ?? ""} {a.biography ? `· ${a.biography}` : ""}
          </div>
          <div className="row" style={{ marginTop: 8, gap: 6 }}>
            {brands.map((b) => (
              <Link key={b.id} to={`/brands/${b.id}`} className={`tag${b.is_own ? " own" : ""}`}>
                {b.name} · {b.role === "shop" ? "официальный аккаунт" : b.status === "tracked" ? LINK_LABEL[b.link_type ?? ""] ?? "креатор" : b.status}
              </Link>
            ))}
          </div>
        </div>
        <div className="row">
          <span className="hint">собран {fmtAgo(a.last_scraped_at)}</span>
          <button onClick={() => refresh.mutate()} disabled={refresh.isPending}>Обновить сейчас</button>
          <a className="btn" href={`https://www.instagram.com/${a.username}/`} target="_blank" rel="noreferrer">Instagram ↗</a>
        </div>
      </div>

      <div className="grid-kpi dense">
        <KpiTile label="Подписчики" value={fmtCompact(snapshot?.followers_count)} delta={<Signed v={st?.followers_delta_30d ?? null} suffix=" за 30 дн." />} />
        <KpiTile label="Δ подписчиков за 7 дн." value={<Signed v={st?.followers_delta_7d ?? null} />} />
        <KpiTile label="Reels в базе" value={fmtInt(media.length)} delta={<span className="muted">постов всего: {fmtInt(snapshot?.media_count)}</span>} />
        <KpiTile label="Публикует в неделю" value={st?.posts_per_week_90d ? fmtDec(Number(st.posts_per_week_90d)) : "—"} delta={<span className="muted">за 7 / 30 / 90 дн.: {st?.reels_7d ?? 0} / {st?.reels_30d ?? 0} / {st?.reels_90d ?? 0}</span>} />
        <KpiTile label="Среднее (20 посл.)" value={fmtCompact(st?.avg_views_20 ?? null)} />
        <KpiTile label="Медиана (20 посл.)" value={fmtCompact(stats.m20)} delta={stats.trend ? <span className={stats.trend >= 1 ? "up" : "down"}>{stats.trend >= 1 ? "▲" : "▼"} {fmtRatio(stats.trend, 2)} к 20 предыдущим</span> : undefined} />
        <KpiTile label="В среднем просмотров в сутки" value={fmtCompact(st?.views_per_day_30d ?? null)} delta={<span className="muted">за 30 дн.: {fmtCompact(st?.views_30d ?? null)}</span>} />
        <KpiTile label="Максимум / P90" value={`${fmtCompact(st?.max_views ?? null)}`} delta={<span className="muted">P90 {fmtCompact(st?.p90_views ?? null)}</span>} />
        <KpiTile label="Всего просмотров" value={fmtCompact(st?.total_views ?? null)} delta={<span className="muted">по всем Reels в базе</span>} />
        <KpiTile label="Стабильность" value={st?.cv_views_20 ? fmtDec(Number(st.cv_views_20), 2) : "—"} hint="σ / среднее по 20 последним: меньше — стабильнее" delta={<span className="muted">{num(st?.cv_views_20) === null ? "" : num(st?.cv_views_20)! < 0.6 ? "стабильный" : num(st?.cv_views_20)! < 1.2 ? "умеренный разброс" : "сильный разброс"}</span>} />
        <KpiTile label="Всплесков" value={fmtInt(stats.spikes)} delta={<span className="muted">hit rate {fmtPct(num(st?.hit_rate))} · viral {st?.viral_total ?? 0}</span>} />
        <KpiTile label="Лучший всплеск" value={fmtRatio(num(st?.best_ratio))} />
        <KpiTile label="ER (медиана)" value={fmtPct(num(st?.er_median_20), 2)} delta={<span className="muted">лайков {fmtCompact(st?.avg_likes_20 ?? null)} · комм. {fmtCompact(st?.avg_comments_20 ?? null)}</span>} />
        <KpiTile label="Охват / подписчики" value={fmtPct(num(st?.views_to_followers), 0)} hint="медиана просмотров / подписчики" />
        <KpiTile label="Средняя длительность" value={num(st?.avg_duration_s) === null ? "—" : `${Math.round(num(st?.avg_duration_s)!)} с`} />
        <KpiTile label="Партнёрских / свой звук" value={`${fmtPct(num(st?.paid_share), 0)} / ${fmtPct(num(st?.original_audio_share), 0)}`} />
        <KpiTile label="Первый ролик в базе" value={<span style={{ fontSize: 18 }}>{fmtDate(st?.first_reel_at ?? null)}</span>} delta={<span className="muted">последний {fmtAgo(st?.last_reel_at ?? null)}</span>} />
      </div>

      <div className="grid2">
        <div className="card">
          <h2>Прирост просмотров по дням</h2>
          {series.data?.views.length ? <Chart option={viewsOption} height={220} /> : <Empty>Ещё нет ежедневных снимков.</Empty>}
          <div className="hint">Сумма по всем роликам креатора. Просмотры, набранные до начала наблюдения, сюда не входят.</div>
        </div>
        <div className="card">
          <h2>Подписчики</h2>
          {series.data?.followers.length ? <Chart option={followersOption} height={220} /> : <Empty>Нет снимков профиля.</Empty>}
        </div>
        <div className="card">
          <h2>Медиана просмотров по часу публикации (МСК)</h2>
          {series.data?.by_hour.length ? <Chart option={hoursOption} height={220} /> : <Empty>Нет данных.</Empty>}
          <div className="hint">Синие столбцы — часы, где креатор набирает не меньше 80% от лучшего результата.</div>
        </div>
        <div className="card flush">
          <div className="card-head"><h2>Хэштеги креатора</h2><span className="hint">использованы 2+ раза</span></div>
          {series.data?.hashtags.length ? (
            <table>
              <thead><tr><th>Хэштег</th><th className="r">Роликов</th><th className="r">Медиана</th><th className="r">От уровня автора</th></tr></thead>
              <tbody>
                {series.data.hashtags.map((h) => (
                  <tr key={h.tag}>
                    <td>#{h.tag}</td>
                    <td className="r">{h.reels}</td>
                    <td className="r">{fmtCompact(h.median_views)}</td>
                    <td className="r"><span className={(num(h.median_ratio) ?? 1) >= 1 ? "up" : "down"}>{fmtRatio(num(h.median_ratio))}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <Empty>Повторяющихся хэштегов нет.</Empty>}
        </div>
      </div>

      <div className="card">
        <h2>Просмотры роликов во времени</h2>
        {media.length ? <Chart option={option} height={300} /> : <Empty>Ролики ещё не собраны — идёт загрузка истории.</Empty>}
        <div className="hint">Логарифмическая шкала. Наведите на точку — подпись, просмотры и базовый уровень автора.</div>
      </div>

      <div className="stack" style={{ gap: 12 }}>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2 style={{ margin: 0 }}>Ролики</h2>
          <div className="row">
          <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Сортировка роликов">
            {Object.entries(SORTS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <label className="check"><input type="checkbox" checked={onlySpikes === "1"} onChange={(e) => setOnlySpikes(e.target.checked ? "1" : null)} /> Только взлетевшие (×2 и выше)</label>
          </div>
        </div>
        {shown.length ? <div className="media-grid">{shown.map((m) => <MediaCard key={m.media_pk} m={m} showOwner={false} />)}</div> : <Empty>Нет роликов.</Empty>}
      </div>

      <div className="card flush">
        <div className="card-head"><h2>Последние задачи парсера</h2></div>
        <table>
          <thead><tr><th>Задача</th><th>Статус</th><th>Попыток</th><th>Завершена</th><th>Ошибка</th></tr></thead>
          <tbody>
            {tasks.map((t) => (
              <tr key={t.id}>
                <td>{TASK_LABEL[t.type] ?? t.type}</td>
                <td><span className={`tag${t.status === "failed" ? " crit" : t.status === "succeeded" ? " good" : ""}`}>{STATUS_LABEL[t.status] ?? t.status}</span></td>
                <td className="num">{t.attempts}</td>
                <td>{fmtDateTime(t.finished_at)}</td>
                <td className="small" style={{ color: "var(--bad)" }}>{t.last_error ?? ""}</td>
              </tr>
            ))}
            {!tasks.length && <tr><td colSpan={5} className="muted">Задач не было</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}

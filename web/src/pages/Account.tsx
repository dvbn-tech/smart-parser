import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { EChartsOption } from "echarts";
import { useCallback, useMemo } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type AccountDetail, type MediaRow } from "../api";
import { Chart, chartChrome, cssVar } from "../components/Chart";
import { Empty, ErrorBox, KpiTile, Loading, MediaCard, toast, useParam } from "../components/ui";
import { CATEGORY_LABEL, LINK_LABEL, STATUS_LABEL, TASK_LABEL, fmtAgo, fmtCompact, fmtDateTime, fmtInt, fmtRatio } from "../format";

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
  const shown = onlySpikes === "1" ? media.filter((m) => ["high", "strong", "viral"].includes(m.spike_category ?? "")) : media;

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

      <div className="grid-kpi">
        <KpiTile label="Подписчики" value={fmtCompact(snapshot?.followers_count)} />
        <KpiTile label="Reels в базе" value={fmtInt(media.length)} delta={<span className="muted">постов всего: {fmtInt(snapshot?.media_count)}</span>} />
        <KpiTile label="Медиана 20 последних" value={fmtCompact(stats.m20)} delta={stats.trend ? <span className={stats.trend >= 1 ? "up" : "down"}>{stats.trend >= 1 ? "▲" : "▼"} {fmtRatio(stats.trend)} к 20 предыдущим</span> : undefined} />
        <KpiTile label="Всплесков" value={fmtInt(stats.spikes)} delta={<span className="muted">hit rate {stats.hit === null ? "—" : `${Math.round(stats.hit * 100)}%`}</span>} />
      </div>

      <div className="card">
        <h2>Просмотры роликов во времени</h2>
        {media.length ? <Chart option={option} height={300} /> : <Empty>Ролики ещё не собраны — идёт загрузка истории.</Empty>}
        <div className="hint">Логарифмическая шкала. Наведите на точку — подпись, просмотры и базовый уровень автора.</div>
      </div>

      <div className="stack" style={{ gap: 12 }}>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2 style={{ margin: 0 }}>Ролики</h2>
          <label className="check"><input type="checkbox" checked={onlySpikes === "1"} onChange={(e) => setOnlySpikes(e.target.checked ? "1" : null)} /> Только взлетевшие (×2 и выше)</label>
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

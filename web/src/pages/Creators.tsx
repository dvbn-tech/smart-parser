import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Brand, type CreatorStats, type Num } from "../api";
import { Empty, ErrorBox, KpiTile, Loading, PeriodPicker, SortTable, downloadCsv, useParam, type Column } from "../components/ui";
import { LINK_LABEL, fmtAgo, fmtCompact, fmtDate, fmtDec, fmtInt, fmtPct, fmtRatio } from "../format";

const n = (v: Num | undefined): number | null => (v === null || v === undefined ? null : Number(v));

function Signed({ v }: { v: number | null }) {
  if (v === null) return <span className="muted">—</span>;
  if (v === 0) return <span className="muted">0</span>;
  return <span className={v > 0 ? "up" : "down"}>{v > 0 ? "▲ +" : "▼ "}{fmtCompact(Math.abs(v))}</span>;
}

function Trend({ v }: { v: number | null }) {
  if (v === null) return <span className="muted">—</span>;
  return <span className={v >= 1 ? "up" : "down"}>{v >= 1 ? "▲" : "▼"} {fmtRatio(v, 2)}</span>;
}

type Group = "main" | "period" | "views" | "engagement" | "rhythm" | "spikes" | "audience";
const GROUPS: { key: Group; label: string }[] = [
  { key: "main", label: "Основное" },
  { key: "period", label: "За период" },
  { key: "views", label: "Просмотры" },
  { key: "spikes", label: "Всплески" },
  { key: "engagement", label: "Вовлечённость" },
  { key: "rhythm", label: "Регулярность и формат" },
  { key: "audience", label: "Аудитория" },
];

type Col = Column<CreatorStats> & { groups: Group[] };

function columns(days: number): Col[] {
  const num = (key: keyof CreatorStats, label: string, groups: Group[], fmt: (v: number | null) => string = fmtCompact, title?: string): Col => ({
    key: String(key),
    label,
    right: true,
    groups,
    title,
    sort: (r) => n(r[key] as Num),
    csv: (r) => n(r[key] as Num),
    render: (r) => fmt(n(r[key] as Num)),
  });
  return [
    {
      key: "user",
      label: "Креатор",
      groups: ["main", "period", "views", "engagement", "rhythm", "spikes", "audience"],
      sort: (r) => r.username,
      csv: (r) => r.username,
      render: (r) => (
        <span className="row" style={{ gap: 6, flexWrap: "nowrap" }}>
          <Link to={`/accounts/${r.user_pk}`} style={{ fontWeight: 600 }}>@{r.username}</Link>
          {r.is_own_creator && <span className="tag own">наш</span>}
          {r.account_status !== "active" && <span className="tag crit">{r.account_status}</span>}
        </span>
      ),
    },
    {
      key: "brands",
      label: "Бренд",
      groups: ["main"],
      sort: (r) => r.brands.map((b) => b.name).join(","),
      csv: (r) => r.brands.map((b) => b.name).join(", "),
      render: (r) => (
        <span className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
          {r.brands.map((b) => (
            <span key={b.id} className={`tag${b.is_own ? " own" : ""}`} title={b.link_type ? LINK_LABEL[b.link_type] : ""}>{b.name}</span>
          ))}
        </span>
      ),
    },
    num("followers", "Подписчики", ["main", "audience"]),
    { key: "fd30", label: "Δ подписчиков 30 дн.", right: true, groups: ["main", "audience"], sort: (r) => r.followers_delta_30d, csv: (r) => r.followers_delta_30d, render: (r) => <Signed v={r.followers_delta_30d} /> },
    num("p_views_gained", `Просмотры за ${days} дн.`, ["main", "period"], fmtCompact, "прирост просмотров всех роликов креатора за даты периода"),
    num("p_reels", `Роликов за ${days} дн.`, ["main", "period"], fmtInt),
    num("avg_views_20", "Среднее (20 посл.)", ["main", "views"], fmtCompact, "средние просмотры 20 последних Reels"),
    num("median_views_20", "Медиана (20 посл.)", ["main", "views"], fmtCompact, "медиана просмотров 20 последних Reels — «обычный» уровень креатора"),
    { key: "trend", label: "Тренд", right: true, groups: ["main", "views"], title: "медиана 20 последних / медиана 20 предыдущих", sort: (r) => n(r.trend), csv: (r) => n(r.trend), render: (r) => <Trend v={n(r.trend)} /> },
    num("views_per_day_30d", "В среднем в сутки", ["main", "views"], fmtCompact, "Σ прироста просмотров за 30 дней / 30"),
    num("spikes_total", "Всплесков", ["main", "spikes"], fmtInt),
    num("hit_rate", "Hit rate", ["main", "spikes"], (v) => fmtPct(v), "доля роликов со всплеском ×2 и выше"),
    { key: "last", label: "Последний ролик", groups: ["main", "rhythm"], sort: (r) => r.last_reel_at, csv: (r) => r.last_reel_at, render: (r) => <span className="ink2">{fmtAgo(r.last_reel_at)}</span> },

    num("p_avg_views", "Среднее за период", ["period"]),
    num("p_median_views", "Медиана за период", ["period"]),
    num("p_max_views", "Максимум за период", ["period"]),
    num("p_spikes", "Всплесков за период", ["period"], fmtInt),
    num("p_viral", "Viral за период", ["period"], fmtInt),
    num("p_best_ratio", "Лучший × за период", ["period"], fmtRatio),
    num("p_er", "ER за период", ["period"], (v) => fmtPct(v, 2)),

    num("median_views_prev_20", "Медиана (20 пред.)", ["views"]),
    num("p90_views", "P90", ["views"], fmtCompact, "90% роликов набрали меньше"),
    num("max_views", "Максимум", ["views"]),
    num("min_views_20", "Минимум (20 посл.)", ["views"]),
    num("total_views", "Всего просмотров", ["views"], fmtCompact, "сумма текущих просмотров всех Reels в базе"),
    num("views_30d", "Прирост за 30 дн.", ["views"]),
    num("cv_views_20", "Разброс", ["views"], (v) => fmtDec(v, 2), "σ / среднее по 20 последним: чем больше, тем менее стабилен креатор"),

    num("spikes_90d", "Всплесков за 90 дн.", ["spikes"], fmtInt),
    num("viral_total", "Viral (×10+)", ["spikes"], fmtInt),
    num("best_ratio", "Лучший всплеск", ["spikes"], fmtRatio),

    num("er_median_20", "ER (медиана)", ["engagement"], (v) => fmtPct(v, 2), "(лайки + комментарии + репосты) / просмотры"),
    num("avg_likes_20", "Лайков в среднем", ["engagement"]),
    num("avg_comments_20", "Комментариев в среднем", ["engagement"]),
    num("views_to_followers", "Охват / подписчики", ["engagement", "audience"], (v) => fmtPct(v, 0), "медиана просмотров / подписчики"),

    num("reels_total", "Reels в базе", ["rhythm"], fmtInt),
    num("reels_7d", "За 7 дн.", ["rhythm"], fmtInt),
    num("reels_30d", "За 30 дн.", ["rhythm"], fmtInt),
    num("reels_90d", "За 90 дн.", ["rhythm"], fmtInt),
    num("posts_per_week_90d", "В неделю", ["rhythm"], (v) => (v === null ? "—" : fmtDec(v)), "роликов в неделю за 90 дней"),
    num("avg_duration_s", "Длительность", ["rhythm"], (v) => (v === null ? "—" : `${Math.round(v)} с`)),
    num("paid_share", "Партнёрских", ["rhythm"], (v) => fmtPct(v, 0)),
    num("original_audio_share", "Свой звук", ["rhythm"], (v) => fmtPct(v, 0)),
    { key: "first", label: "Первый ролик в базе", groups: ["rhythm"], sort: (r) => r.first_reel_at, csv: (r) => r.first_reel_at, render: (r) => fmtDate(r.first_reel_at) },

    { key: "fd7", label: "Δ подписчиков 7 дн.", right: true, groups: ["audience"], sort: (r) => r.followers_delta_7d, csv: (r) => r.followers_delta_7d, render: (r) => <Signed v={r.followers_delta_7d} /> },
    { key: "growth", label: "Рост за 30 дн., %", right: true, groups: ["audience"], sort: (r) => (r.followers && r.followers_delta_30d !== null ? r.followers_delta_30d / (r.followers - r.followers_delta_30d) : null), csv: (r) => (r.followers && r.followers_delta_30d !== null ? r.followers_delta_30d / (r.followers - r.followers_delta_30d) : null), render: (r) => (r.followers && r.followers_delta_30d !== null ? fmtPct(r.followers_delta_30d / (r.followers - r.followers_delta_30d)) : "—") },
    { key: "cat", label: "Категория", groups: ["audience"], sort: (r) => r.category, csv: (r) => r.category, render: (r) => <span className="ink2">{r.category ?? "—"}</span> },
  ];
}

export default function CreatorsPage() {
  const [days, setDays] = useParam("days", "30");
  const [scope, setScope] = useParam("scope", "all");
  const [brandsParam, setBrands] = useParam("brands", "");
  const [groupParam, setGroup] = useParam("cols", "main");
  const [ownOnly, setOwnOnly] = useParam("own", "0");
  const [search, setSearch] = useState("");
  const selected = brandsParam ? brandsParam.split(",").map(Number) : [];
  const group = groupParam as Group | "all";

  const brands = useQuery({ queryKey: ["brands"], queryFn: () => api.get<Brand[]>("/brands") });
  const qs = new URLSearchParams({ days, scope });
  selected.forEach((id) => qs.append("brand_id", String(id)));
  const q = useQuery({ queryKey: ["creators", qs.toString()], queryFn: () => api.get<{ items: CreatorStats[] }>(`/creators?${qs}`) });

  const allCols = useMemo(() => columns(Number(days)), [days]);
  const cols = group === "all" ? allCols : allCols.filter((c) => c.groups.includes(group));
  const rows = useMemo(() => {
    let r = q.data?.items ?? [];
    if (ownOnly === "1") r = r.filter((x) => x.is_own_creator);
    const s = search.trim().toLowerCase().replace(/^@/, "");
    if (s) r = r.filter((x) => x.username.includes(s) || (x.full_name ?? "").toLowerCase().includes(s));
    return r;
  }, [q.data, ownOnly, search]);

  const sum = (f: (r: CreatorStats) => number | null) => rows.reduce((s, r) => s + (f(r) ?? 0), 0);
  const medians = rows.map((r) => r.median_views_20).filter((v): v is number => v !== null).sort((a, b) => a - b);
  const hit = rows.map((r) => n(r.hit_rate)).filter((v): v is number => v !== null);
  const toggleBrand = (id: number) => {
    const next = selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id];
    setBrands(next.length ? next.join(",") : null);
  };

  return (
    <div className="stack" style={{ gap: 16 }}>
      <div className="head">
        <div>
          <h1>Креаторы</h1>
          <div className="sub">Все отслеживаемые креаторы брендов: просмотры, стабильность, всплески, вовлечённость, регулярность и рост аудитории</div>
        </div>
        <button onClick={() => downloadCsv(`creators_${days}d.csv`, rows, allCols)} disabled={!rows.length}>Выгрузить CSV (все колонки)</button>
      </div>

      <div className="card stack" style={{ gap: 12 }}>
        <div className="row" style={{ gap: 12 }}>
          <PeriodPicker value={Number(days)} onChange={(d) => setDays(String(d))} />
          <div className="seg">
            {[["all", "Все"], ["competitors", "Конкуренты"], ["own", "Наш бренд"]].map(([v, l]) => (
              <button key={v} className={scope === v ? "on" : ""} onClick={() => setScope(v)}>{l}</button>
            ))}
          </div>
          <label className="check"><input type="checkbox" checked={ownOnly === "1"} onChange={(e) => setOwnOnly(e.target.checked ? "1" : null)} /> только наши креаторы</label>
          <input className="search" placeholder="Поиск по нику или имени" value={search} onChange={(e) => setSearch(e.target.value)} />
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

      {q.isLoading && <Loading h={300} />}
      {q.error && <ErrorBox error={q.error} />}
      {q.data && (
        <>
          <div className="grid-kpi dense">
            <KpiTile label="Креаторов" value={fmtInt(rows.length)} delta={<span className="muted">наших: {rows.filter((r) => r.is_own_creator).length}</span>} />
            <KpiTile label={`Просмотры за ${days} дн.`} value={fmtCompact(sum((r) => r.p_views_gained))} />
            <KpiTile label={`Роликов за ${days} дн.`} value={fmtInt(sum((r) => r.p_reels))} delta={<span className="muted">{rows.length ? fmtDec(sum((r) => r.p_reels) / rows.length) : "—"} на креатора</span>} />
            <KpiTile label="Типичная медиана креатора" value={fmtCompact(medians.length ? medians[Math.floor(medians.length / 2)] : null)} delta={<span className="muted">медиана медиан 20 последних</span>} />
            <KpiTile label="Средний hit rate" value={fmtPct(hit.length ? hit.reduce((a, b) => a + b, 0) / hit.length : null)} />
            <KpiTile label="Растут / падают" value={`${rows.filter((r) => (n(r.trend) ?? 1) > 1.05).length} / ${rows.filter((r) => (n(r.trend) ?? 1) < 0.95).length}`} delta={<span className="muted">тренд медианы ±5%</span>} />
            <KpiTile label="Суммарная аудитория" value={fmtCompact(sum((r) => r.followers))} delta={<Signed v={sum((r) => r.followers_delta_30d)} />} />
          </div>

          <div className="card flush">
            <div className="card-head" style={{ flexWrap: "wrap" }}>
              <div className="row" style={{ gap: 6 }}>
                {GROUPS.map((g) => (
                  <button key={g.key} className={`chip${group === g.key ? " on" : ""}`} onClick={() => setGroup(g.key)}>{g.label}</button>
                ))}
                <button className={`chip${group === "all" ? " on" : ""}`} onClick={() => setGroup("all")}>Все колонки</button>
              </div>
              <span className="hint">нажмите на заголовок, чтобы отсортировать</span>
            </div>
            {rows.length ? (
              <div className="compact">
                <SortTable<CreatorStats> rows={rows} rowKey={(r) => r.user_pk} columns={cols} initial={group === "period" ? "p_views_gained" : "p_views_gained"} sticky />
              </div>
            ) : (
              <Empty>Креаторов под эти фильтры нет.</Empty>
            )}
          </div>
        </>
      )}
    </div>
  );
}

import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, type Brand, type MediaRow } from "../api";
import { Empty, ErrorBox, Loading, MediaCard, PeriodPicker, SortTable, SpikeBadge, useParam } from "../components/ui";
import { fmtCompact, fmtDate, igUrl } from "../format";

const SCOPES = [
  { v: "all", label: "Все" },
  { v: "competitors", label: "Конкуренты" },
  { v: "own", label: "Наш бренд" },
];
const CATS = [
  { v: "high", label: "×2+" },
  { v: "strong", label: "×5+" },
  { v: "viral", label: "×10+" },
];
const SORTS = [
  { v: "ratio", label: "по силе всплеска" },
  { v: "views", label: "по просмотрам" },
  { v: "date", label: "сначала новые" },
];

export default function AnomaliesPage() {
  const [days, setDays] = useParam("days", "30");
  const [scope, setScope] = useParam("scope", "all");
  const [cat, setCat] = useParam("cat", "high");
  const [sort, setSort] = useParam("sort", "ratio");
  const [brandsParam, setBrands] = useParam("brands", "");
  const [view, setView] = useParam("view", "cards");
  const selected = brandsParam ? brandsParam.split(",").map(Number) : [];

  const brands = useQuery({ queryKey: ["brands"], queryFn: () => api.get<Brand[]>("/brands") });
  const qs = new URLSearchParams({ days, scope, min_category: cat, sort, limit: "300" });
  selected.forEach((id) => qs.append("brand_id", String(id)));
  const data = useQuery({ queryKey: ["anomalies", qs.toString()], queryFn: () => api.get<{ items: MediaRow[] }>(`/anomalies?${qs}`) });

  const toggleBrand = (id: number) => {
    const next = selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id];
    setBrands(next.length ? next.join(",") : null);
  };
  const csvQs = new URLSearchParams(qs);
  csvQs.set("format", "csv");
  csvQs.set("limit", "5000");

  return (
    <div className="stack" style={{ gap: 16 }}>
      <div className="head">
        <div>
          <h1>Аномалии</h1>
          <div className="sub">Ролики, набравшие в разы больше обычного для своего автора (медиана 20 предыдущих Reels)</div>
        </div>
        <a className="btn" href={`/api/v1/anomalies?${csvQs}`}>Выгрузить CSV</a>
      </div>

      <div className="card stack" style={{ gap: 12 }}>
        <div className="row" style={{ gap: 12 }}>
          <PeriodPicker value={Number(days)} onChange={(d) => setDays(String(d))} />
          <div className="seg" role="group" aria-label="Чьи ролики">
            {SCOPES.map((s) => (
              <button key={s.v} className={scope === s.v ? "on" : ""} onClick={() => setScope(s.v)}>{s.label}</button>
            ))}
          </div>
          <div className="seg" role="group" aria-label="Минимальный всплеск">
            {CATS.map((c) => (
              <button key={c.v} className={cat === c.v ? "on" : ""} onClick={() => setCat(c.v)}>{c.label}</button>
            ))}
          </div>
          <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Сортировка">
            {SORTS.map((s) => <option key={s.v} value={s.v}>{s.label}</option>)}
          </select>
          <div className="seg" style={{ marginLeft: "auto" }}>
            <button className={view === "cards" ? "on" : ""} onClick={() => setView("cards")}>Карточки</button>
            <button className={view === "table" ? "on" : ""} onClick={() => setView("table")}>Таблица</button>
          </div>
        </div>
        {brands.data && (
          <div className="row" style={{ gap: 6 }}>
            <span className="hint">Бренды:</span>
            {brands.data.map((b) => (
              <button key={b.id} className={`chip${selected.includes(b.id) ? " on" : ""}`} onClick={() => toggleBrand(b.id)}>
                {b.name}{b.is_own ? " · наш" : ""}
              </button>
            ))}
            {selected.length > 0 && <button className="ghost small" onClick={() => setBrands(null)}>сбросить</button>}
          </div>
        )}
      </div>

      {data.isLoading && <Loading h={300} />}
      {data.error && <ErrorBox error={data.error} />}
      {data.data && data.data.items.length === 0 && <Empty>Под эти фильтры всплесков нет. Попробуйте период длиннее или порог ниже.</Empty>}
      {data.data && data.data.items.length > 0 && (
        <>
          <div className="hint">Найдено: {data.data.items.length}{data.data.items.length >= 300 ? " (показаны первые 300, полный список — в CSV)" : ""}</div>
          {view === "cards" ? (
            <div className="media-grid">
              {data.data.items.map((m) => <MediaCard key={m.media_pk} m={m} />)}
            </div>
          ) : (
            <div className="card flush">
              <SortTable<MediaRow>
                rows={data.data.items}
                rowKey={(m) => m.media_pk}
                columns={[
                  { key: "spike", label: "Всплеск", sort: (m) => m.spike_ratio, render: (m) => <SpikeBadge m={m} /> },
                  { key: "owner", label: "Автор", sort: (m) => m.owner_username ?? "", render: (m) => <Link to={`/accounts/${m.owner_user_pk}`}>@{m.owner_username}</Link> },
                  { key: "brands", label: "Бренд", render: (m) => m.brands?.map((b) => <span key={b.id} className={`tag${b.is_own ? " own" : ""}`} style={{ marginRight: 4 }}>{b.name}</span>) },
                  { key: "views", label: "Просмотры", right: true, sort: (m) => m.views, render: (m) => fmtCompact(m.views) },
                  { key: "base", label: "Обычно у автора", right: true, sort: (m) => m.baseline_median, render: (m) => fmtCompact(m.baseline_median) },
                  { key: "date", label: "Дата", sort: (m) => m.taken_at, render: (m) => <span style={{ whiteSpace: "nowrap" }}>{fmtDate(m.taken_at)}</span> },
                  { key: "caption", label: "Подпись", render: (m) => <span className="ink2" style={{ display: "inline-block", maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={m.caption ?? ""}>{m.caption}</span> },
                  { key: "link", label: "", render: (m) => <a href={igUrl(m.shortcode)} target="_blank" rel="noreferrer" style={{ whiteSpace: "nowrap" }}>Instagram ↗</a> },
                ]}
              />
            </div>
          )}
        </>
      )}
    </div>
  );
}

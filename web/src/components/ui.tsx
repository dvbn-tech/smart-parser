import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import type { MediaRow } from "../api";
import { CATEGORY_LABEL, METHOD_LABEL, fmtAgo, fmtCompact, fmtDate, fmtDuration, fmtInt, fmtRatio, igUrl } from "../format";

export function KpiTile({ label, value, delta, hint }: { label: string; value: ReactNode; delta?: ReactNode; hint?: string }) {
  return (
    <div className="card kpi" title={hint}>
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {delta !== undefined && <div className="delta">{delta}</div>}
    </div>
  );
}

/** Изменение к прошлому периоду: стрелка + знак, не только цвет. */
export function Delta({ cur, prev, kind = "pct" }: { cur: number | null; prev: number | null; kind?: "pct" | "pp" }) {
  if (cur === null || prev === null || prev === 0) return <span className="muted">нет данных за прошлый период</span>;
  if (kind === "pp") {
    const d = (cur - prev) * 100;
    const cls = d > 0 ? "up" : d < 0 ? "down" : "muted";
    return <span className={cls}>{d > 0 ? "▲ +" : d < 0 ? "▼ " : ""}{d.toLocaleString("ru-RU", { maximumFractionDigits: 1 })} п.п. к прошлому периоду</span>;
  }
  const d = cur / prev - 1;
  const cls = d > 0 ? "up" : d < 0 ? "down" : "muted";
  return <span className={cls}>{d > 0 ? "▲ +" : d < 0 ? "▼ " : ""}{(d * 100).toLocaleString("ru-RU", { maximumFractionDigits: 0 })}% к прошлому периоду</span>;
}

export function SpikeBadge({ m }: { m: Pick<MediaRow, "spike_ratio" | "spike_category" | "is_early" | "spike_method" | "baseline_median"> }) {
  const cat = m.spike_category ?? "insufficient_data";
  const title = [
    m.baseline_median ? `базовый уровень автора: ${fmtInt(m.baseline_median)}` : null,
    m.spike_method ? METHOD_LABEL[m.spike_method] : null,
    m.is_early ? "ранний всплеск — ролику меньше 7 дней" : null,
  ].filter(Boolean).join("\n");
  if (m.spike_ratio === null) return <span className={`spike ${cat}`} title={title}>{CATEGORY_LABEL[cat] ?? cat}</span>;
  return (
    <span className={`spike ${cat}${m.is_early ? " early" : ""}`} title={title}>
      {fmtRatio(m.spike_ratio)}
      {cat !== "none" && <span style={{ fontWeight: 500 }}>{CATEGORY_LABEL[cat]}</span>}
    </span>
  );
}

function hue(seed: string): number {
  let h = 0;
  for (const c of seed) h = (h * 31 + c.charCodeAt(0)) % 360;
  return h;
}

export function MediaCard({ m, showOwner = true }: { m: MediaRow; showOwner?: boolean }) {
  const h = hue(m.shortcode);
  return (
    <div className="media">
      <a
        className="cover"
        href={igUrl(m.shortcode)}
        target="_blank"
        rel="noreferrer"
        title="Открыть в Instagram"
        style={{ background: `linear-gradient(160deg, hsl(${h} 45% 52%), hsl(${(h + 40) % 360} 50% 28%))`, textDecoration: "none" }}
      >
        <div className="badge-top">
          <SpikeBadge m={m} />
          {m.duration_s ? <span className="dur">{fmtDuration(m.duration_s)}</span> : <span />}
        </div>
        <div className="views">
          {fmtCompact(m.views)}
          <small>просмотров{m.baseline_median ? ` · обычно ${fmtCompact(m.baseline_median)}` : ""}</small>
        </div>
      </a>
      <div className="body">
        <div className="caption" title={m.caption ?? ""}>{m.caption ?? <span className="muted">без подписи</span>}</div>
        <div className="row" style={{ gap: 4 }}>
          {m.brands?.map((b) => (
            <span key={b.id} className={`tag${b.is_own ? " own" : ""}`}>{b.name}</span>
          ))}
          {m.is_paid_partnership && <span className="tag warn">партнёрство</span>}
          {m.is_rocket && <span className="tag">ракета</span>}
        </div>
        <div className="meta">
          {showOwner && m.owner_user_pk ? <Link to={`/accounts/${m.owner_user_pk}`}>@{m.owner_username}</Link> : <span />}
          <span>{fmtDate(m.taken_at)}</span>
        </div>
        <div className="meta" title="лайки · комментарии · репосты">
          <span>♥ {fmtCompact(m.likes ?? null)} · 💬 {fmtCompact(m.comments ?? null)}{m.reshares ? ` · ↗ ${fmtCompact(m.reshares)}` : ""}</span>
          {m.er !== null && <span>ER {(Number(m.er) * 100).toFixed(1)}%</span>}
        </div>
        {(m.audio_title || m.location_name) && (
          <div className="meta">
            <span title={m.audio_artist ?? ""} style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>♪ {m.audio_title ?? "—"}</span>
            {m.location_name && <span>📍 {m.location_name}</span>}
          </div>
        )}
      </div>
    </div>
  );
}

export function Loading({ h = 160 }: { h?: number }) {
  return <div className="skeleton" style={{ height: h }} aria-label="Загрузка" />;
}

export function ErrorBox({ error }: { error: unknown }) {
  return <div className="error">Не удалось загрузить данные: {error instanceof Error ? error.message : String(error)}</div>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Freshness({ at }: { at: string | null | undefined }) {
  const stale = !at || Date.now() - new Date(at).getTime() > 26 * 3600 * 1000;
  return (
    <span className={`freshness${stale ? " stale" : ""}`} title={at ? new Date(at).toLocaleString("ru-RU") : ""}>
      <span className="dot" />
      {stale ? "данные устарели: " : "данные обновлены "}{fmtAgo(at)}
    </span>
  );
}

export const PERIODS = [
  { days: 7, label: "7 дней" },
  { days: 30, label: "30 дней" },
  { days: 90, label: "90 дней" },
  { days: 365, label: "год" },
];

/** Параметр в URL: ссылку можно переслать коллеге, и она откроет тот же вид. */
export function useParam(name: string, fallback: string): [string, (v: string | null) => void] {
  const [params, setParams] = useSearchParams();
  const value = params.get(name) ?? fallback;
  const set = (v: string | null) =>
    setParams(
      (p) => {
        const n = new URLSearchParams(p);
        if (v === null || v === fallback) n.delete(name);
        else n.set(name, v);
        return n;
      },
      { replace: true },
    );
  return [value, set];
}

export function PeriodPicker({ value, onChange }: { value: number; onChange: (d: number) => void }) {
  return (
    <div className="seg" role="group" aria-label="Период">
      {PERIODS.map((p) => (
        <button key={p.days} className={value === p.days ? "on" : ""} onClick={() => onChange(p.days)}>
          {p.label}
        </button>
      ))}
    </div>
  );
}

export interface Column<T> {
  key: string;
  label: string;
  right?: boolean;
  sort?: (row: T) => number | string | null;
  render: (row: T) => ReactNode;
  title?: string;
  /** Значение для выгрузки CSV; без него колонка в выгрузку не попадает. */
  csv?: (row: T) => string | number | null | undefined;
}

export function downloadCsv<T>(filename: string, rows: T[], columns: Column<T>[]) {
  const cols = columns.filter((c) => c.csv);
  const esc = (v: unknown) => {
    const s = v === null || v === undefined ? "" : String(v);
    return /[";\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines = [cols.map((c) => esc(c.label)).join(";"), ...rows.map((r) => cols.map((c) => esc(c.csv!(r))).join(";"))];
  const blob = new Blob(["\ufeff" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

export function SortTable<T>({
  rows,
  columns,
  initial,
  rowKey,
  sticky = false,
  limit,
}: {
  rows: T[];
  columns: Column<T>[];
  initial?: string;
  rowKey: (r: T) => string | number;
  sticky?: boolean;
  limit?: number;
}) {
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 }>({ key: initial ?? "", dir: -1 });
  const sorted = useMemo(() => {
    const col = columns.find((c) => c.key === sort.key);
    if (!col?.sort) return rows;
    const get = col.sort;
    return [...rows].sort((a, b) => {
      const va = get(a);
      const vb = get(b);
      if (va === null) return 1;
      if (vb === null) return -1;
      return (va < vb ? -1 : va > vb ? 1 : 0) * sort.dir;
    });
  }, [rows, columns, sort]);
  const shown = limit ? sorted.slice(0, limit) : sorted;
  return (
    <div className={`table-wrap${sticky ? " sticky-first" : ""}`}>
      <table>
        <thead>
          <tr>
            {columns.map((c) => (
              <th
                key={c.key}
                className={`${c.right ? "r " : ""}${c.sort ? "sortable" : ""}`}
                title={c.title}
                onClick={() => c.sort && setSort((s) => ({ key: c.key, dir: s.key === c.key ? ((-s.dir) as 1 | -1) : -1 }))}
              >
                {c.label}
                {sort.key === c.key ? (sort.dir === -1 ? " ↓" : " ↑") : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {shown.map((r) => (
            <tr key={rowKey(r)}>
              {columns.map((c) => (
                <td key={c.key} className={c.right ? "r" : ""}>{c.render(r)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

let toastSetter: ((m: string | null) => void) | null = null;

export function toast(message: string) {
  toastSetter?.(message);
}

export function ToastHost() {
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => {
    toastSetter = setMsg;
    return () => {
      toastSetter = null;
    };
  }, []);
  useEffect(() => {
    if (!msg) return;
    const t = setTimeout(() => setMsg(null), 3500);
    return () => clearTimeout(t);
  }, [msg]);
  return msg ? <div className="toast" role="status">{msg}</div> : null;
}

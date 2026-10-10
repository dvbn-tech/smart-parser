const nf = new Intl.NumberFormat("ru-RU");

export function fmtInt(v: number | string | null | undefined): string {
  if (v === null || v === undefined || v === "") return "—";
  return nf.format(Math.round(Number(v)));
}

/** 2 400 000 → 2,4 млн; 180 000 → 180 тыс. */
export function fmtCompact(v: number | string | null | undefined): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  const abs = Math.abs(n);
  if (abs >= 1e6) return `${trim(n / 1e6)} млн`;
  if (abs >= 1e3) return `${trim(n / 1e3)} тыс.`;
  return nf.format(Math.round(n));
}

function trim(n: number): string {
  return n.toLocaleString("ru-RU", { maximumFractionDigits: n >= 100 ? 0 : 1 });
}

export function fmtPct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined) return "—";
  return `${(v * 100).toLocaleString("ru-RU", { maximumFractionDigits: digits })}%`;
}

export function fmtRatio(v: number | string | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `×${Number(v).toLocaleString("ru-RU", { maximumFractionDigits: 1 })}`;
}

export function fmtDate(v: string | null | undefined): string {
  if (!v) return "—";
  const d = new Date(v);
  const sameYear = d.getFullYear() === new Date().getFullYear();
  return d.toLocaleDateString("ru-RU", sameYear ? { day: "numeric", month: "short" } : { day: "numeric", month: "short", year: "numeric" });
}

export function fmtDateTime(v: string | null | undefined): string {
  if (!v) return "—";
  return new Date(v).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function fmtAgo(v: string | null | undefined): string {
  if (!v) return "никогда";
  const diff = (Date.now() - new Date(v).getTime()) / 1000;
  if (diff < 0) return `через ${Math.round(-diff / 60)} мин`;
  if (diff < 3600) return `${Math.max(1, Math.round(diff / 60))} мин назад`;
  if (diff < 86400) return `${Math.round(diff / 3600)} ч назад`;
  return `${Math.round(diff / 86400)} дн. назад`;
}

export function fmtDuration(v: number | string | null | undefined): string {
  if (v === null || v === undefined) return "";
  const s = Math.round(Number(v));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export const CATEGORY_LABEL: Record<string, string> = {
  high: "high",
  strong: "strong",
  viral: "viral",
  none: "норма",
  insufficient_data: "мало данных",
};

export const METHOD_LABEL: Record<string, string> = {
  age_matched_7d: "на 7-й день, сравнение с 20 предыдущими на том же возрасте",
  early: "ранний: на текущем возрасте ролика",
  current_views: "по текущим просмотрам (история без ежедневных снимков)",
};

export const LINK_LABEL: Record<string, string> = {
  ambassador: "амбассадор",
  paid: "платная",
  ugc: "UGC",
  reviewer: "обзорщик",
  satellite: "сателлит",
};

export const EVIDENCE_LABEL: Record<string, string> = {
  paid_partnership: "партнёрство",
  collab: "collab",
  usertag: "отметка",
  wb_article: "артикул WB",
  brand_name: "бренд в профиле",
  hashtag: "хэштег",
};

export const TASK_LABEL: Record<string, string> = {
  manual_refresh: "ручное обновление",
  backfill: "вся история",
  profile: "профиль",
  feed_head: "лента (новые)",
  feed_deep: "лента (полная)",
  media_cover: "обложка",
  brand_tagged: "отметки бренда",
  candidate_probe: "проверка кандидата",
  reparse: "пересборка",
  canary: "канарейка",
};

export const STATUS_LABEL: Record<string, string> = {
  pending: "в очереди",
  running: "выполняется",
  succeeded: "готово",
  retry: "повтор",
  deferred: "отложена",
  failed: "ошибка",
};

export function igUrl(shortcode: string): string {
  return `https://www.instagram.com/reel/${shortcode}/`;
}

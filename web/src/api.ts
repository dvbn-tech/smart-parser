export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/v1${path}`, init);
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") message = body.detail;
      else if (Array.isArray(body.detail)) message = body.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      /* тело не JSON */
    }
    throw new ApiError(res.status, message);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "POST",
      headers: body instanceof FormData ? undefined : { "Content-Type": "application/json" },
      body: body instanceof FormData ? body : body === undefined ? undefined : JSON.stringify(body),
    }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  del: (path: string) => request<void>(path, { method: "DELETE" }),
};

export type SpikeCategory = "none" | "high" | "strong" | "viral" | "insufficient_data";

export interface BrandRef {
  id: number;
  name: string;
  is_own: boolean;
  reason: string;
}

export interface MediaRow {
  media_pk: string;
  shortcode: string;
  taken_at: string;
  caption: string | null;
  duration_s: number | null;
  audio_title: string | null;
  is_paid_partnership: boolean | null;
  owner_user_pk?: number;
  owner_username?: string;
  views: number | null;
  views_7d: number | null;
  baseline_median: number | null;
  spike_ratio: number | null;
  spike_category: SpikeCategory | null;
  spike_method: string | null;
  is_early: boolean | null;
  is_rocket: boolean | null;
  er: number | null;
  brands?: BrandRef[];
  missing_since?: string | null;
  likes?: number | null;
  comments?: number | null;
  reshares?: number | null;
  views_per_day?: Num;
  views_before_observation?: number | null;
  audio_artist?: string | null;
  audio_type?: string | null;
  location_name?: string | null;
}

export interface BrandStats {
  id: number;
  name: string;
  is_own: boolean;
  hashtags: string[];
  shop_username: string | null;
  creators: number;
  candidates: number;
  reels: number;
  spikes: number;
  viral: number;
  views: number;
  median_views: number | null;
  active_creators: number;
  prev_reels: number | null;
  prev_spikes: number | null;
  prev_median_views: number | null;
  spike_share: number | null;
  prev_spike_share: number | null;
}

export interface ParserSummary {
  active_accounts: number;
  covered_24h: number;
  queued: number;
  running: number;
  failed_24h: number;
  quarantine: number;
  invalid_24h: number;
  coverage: number | null;
}

export interface Overview {
  data_as_of: string | null;
  days: number;
  brands: BrandStats[];
  weekly: { brand_id: number; week: string; reels: number; spikes: number }[];
  parser: ParserSummary;
}

export interface PendingAccount {
  task_id: number;
  username: string;
  status: string;
  attempts: number;
  last_error: string | null;
  run_after: string;
  role: string;
  person_name: string | null;
  curator: string | null;
  link_type: string | null;
  is_own_creator: boolean;
}

export interface Brand {
  id: number;
  name: string;
  is_own: boolean;
  hashtags: string[];
  username_masks?: string[];
  domains?: string[];
  pending?: number;
  pending_shop?: string | null;
  spike_min_views: number;
  rocket_views: number;
  shop_user_pk: number | null;
  shop_username: string | null;
  creators?: number;
  candidates?: number;
}

export interface CreatorRow {
  user_pk: number;
  username: string;
  full_name: string | null;
  account_status: string;
  last_scraped_at: string | null;
  role: string;
  link_type: string | null;
  status: string;
  is_own_creator: boolean;
  confidence: string | null;
  followers: number | null;
  reels: number | null;
  median_views: number | null;
  spikes: number | null;
  max_ratio: number | null;
  last_reel_at: string | null;
  trend: number | null;
  avg_views_20?: number | null;
  views_per_day_30d?: number | null;
  er_median_20?: Num;
  posts_per_week_90d?: Num;
  followers_delta_30d?: number | null;
  hit_rate?: Num;
}

export interface Evidence {
  kind: string;
  media_pk: number | null;
  value: string;
  weight: number;
}

export interface Candidate {
  brand_id: number;
  brand_name: string;
  user_pk: number;
  username: string;
  full_name: string | null;
  biography: string | null;
  confidence: string | null;
  evidence: Evidence[];
  link_type: string | null;
  first_seen: string | null;
  status: string;
  followers: number | null;
  level: "confirmed" | "likely" | "possible" | null;
}

export interface Task {
  id: number;
  type: string;
  status: string;
  priority: number;
  attempts: number;
  last_error: string | null;
  cursor?: string | null;
  pages_done?: number;
  run_after?: string;
  lease_until?: string | null;
  finished_at: string | null;
  created_at?: string;
  user_pk?: number | null;
  username?: string | null;
}

export interface AccountDetail {
  account: {
    user_pk: number;
    username: string;
    full_name: string | null;
    biography: string | null;
    status: string;
    is_private: boolean;
    is_verified: boolean;
    is_business: boolean;
    category: string | null;
    last_scraped_at: string | null;
    added_at: string;
  };
  snapshot: { followers_count: number; following_count: number; media_count: number; snapshot_date: string } | null;
  brands: { id: number; name: string; is_own: boolean; role: string; status: string; link_type: string | null; is_own_creator: boolean }[];
  media: MediaRow[];
  tasks: Task[];
}

export interface ParserStatus {
  data_as_of: string | null;
  summary: ParserSummary;
  queue: { status: string; priority: number; n: number }[];
  tasks: Task[];
  quarantine: { id: number; media_pk: string; shortcode: string | null; username: string | null; snapshot_date: string; play_count: number; reason: string; raw_response_id: number }[];
  invalid_responses: { id: number; request_kind: string; http_status: number | null; shape_fingerprint: string | null; parse_error: string | null; s3_key: string; received_at: string }[];
  problem_accounts: { user_pk: number; username: string; status: string; last_scraped_at: string | null }[];
}

export type Num = number | string | null;

export interface BrandPeriod {
  brand_id: number;
  reels: number;
  active_creators: number;
  views: number;
  avg_views: number | null;
  median_views: number | null;
  p90_views: number | null;
  max_views: number | null;
  spikes: number;
  viral: number;
  million_plus: number;
  er_median: number | null;
  likes: number;
  comments: number;
  avg_duration_s: Num;
  paid_share: Num;
  original_audio_share: Num;
  median_ratio: number | null;
  views_gained: number | null;
}

export interface OverviewBrand {
  id: number;
  name: string;
  is_own: boolean;
  hashtags: string[];
  shop_username: string | null;
  shop_user_pk: number | null;
  creators: number;
  own_creators: number;
  candidates: number;
  shop_followers: number | null;
  creators_followers: Num;
  cur: BrandPeriod | null;
  prev: BrandPeriod | null;
}

export interface Leader {
  user_pk: number;
  username: string;
  brand_id: number;
  brand_name: string;
  is_own: boolean;
  reels: number;
  median_views: number | null;
  avg_views: number | null;
  spikes: number;
  views_gained: number | null;
  followers: number | null;
  median_views_20: number | null;
  trend: Num;
}

export interface OverviewV2 {
  data_as_of: string | null;
  days: number;
  observed_since: string | null;
  brands: OverviewBrand[];
  daily: { brand_id: number; date: string; views: number }[];
  weekly: { brand_id: number; week: string; reels: number; spikes: number; median_views: number | null }[];
  leaders: Leader[];
}

export interface CreatorStats {
  user_pk: number;
  username: string;
  full_name: string | null;
  account_status: string;
  is_verified: boolean;
  category: string | null;
  last_scraped_at: string | null;
  brands: { id: number; name: string; is_own: boolean; role: string; link_type: string | null; is_own_creator: boolean }[];
  is_own_creator: boolean;
  is_own_brand: boolean;
  reels_total: number | null;
  reels_7d: number | null;
  reels_30d: number | null;
  reels_90d: number | null;
  posts_per_week_90d: Num;
  avg_views_20: number | null;
  median_views_20: number | null;
  median_views_prev_20: number | null;
  trend: Num;
  p90_views: number | null;
  max_views: number | null;
  min_views_20: number | null;
  total_views: number | null;
  views_30d: number | null;
  views_per_day_30d: number | null;
  cv_views_20: Num;
  avg_likes_20: number | null;
  avg_comments_20: number | null;
  er_median_20: Num;
  spikes_total: number | null;
  spikes_90d: number | null;
  viral_total: number | null;
  hit_rate: Num;
  best_ratio: Num;
  avg_duration_s: Num;
  paid_share: Num;
  original_audio_share: Num;
  followers: number | null;
  followers_delta_7d: number | null;
  followers_delta_30d: number | null;
  views_to_followers: Num;
  first_reel_at: string | null;
  last_reel_at: string | null;
  p_reels: number | null;
  p_avg_views: number | null;
  p_median_views: number | null;
  p_max_views: number | null;
  p_spikes: number | null;
  p_viral: number | null;
  p_best_ratio: Num;
  p_er: Num;
  p_views_gained: number | null;
}

export interface InsightRow {
  key: string | number;
  reels: number;
  creators: number;
  median_ratio: number | null;
  avg_ratio: Num;
  spike_rate: Num;
  spikes: number;
  median_views: number | null;
  median_er: number | null;
  lift?: number | null;
  wilson_low?: number;
  is_original?: boolean;
}

export interface Insights {
  days: number;
  total: InsightRow;
  by_hour: InsightRow[];
  by_weekday: InsightRow[];
  by_duration: InsightRow[];
  features: InsightRow[];
  caption_length: InsightRow[];
  hashtags: InsightRow[];
  audio: InsightRow[];
  locations: InsightRow[];
  ratio_histogram: { key: string; reels: number }[];
}

export interface AccountSeries {
  followers: { date: string; followers: number }[];
  views: { date: string; views: number }[];
  stats: CreatorStats | null;
  hashtags: { tag: string; reels: number; median_ratio: number | null; median_views: number | null }[];
  by_hour: { hour: number; reels: number; median_views: number | null }[];
}

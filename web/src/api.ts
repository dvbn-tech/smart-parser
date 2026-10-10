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

export interface Brand {
  id: number;
  name: string;
  is_own: boolean;
  hashtags: string[];
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

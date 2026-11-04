// Thin typed client for the Serpent HTTP API. No dependencies.

export type Role = 'none' | 'read' | 'admin';

export interface Account {
  id: number;
  label: string;
  provider_id: number | null;
  status: 'active' | 'disabled' | 'invalid';
  quota_limit: number;
  used: number;
  remaining: number;
  available: number;
  percent_used: number;
  in_flight: number;
  ok: number;
  failed: number;
  refunded: number;
  avg_latency_ms: number | null;
  last_used_at: string | null;
  last_error: string | null;
  cooldown_until: string | null;
  on_cooldown: boolean;
  key_hint?: string;
  notes: string | null;
}

export interface Provider {
  id: number;
  slug: string;
  name: string;
  preset: string | null;
  base_url: string;
  auth_style: 'header' | 'query' | 'bearer';
  auth_header_name: string;
  auth_param_name: string;
  enabled: boolean;
}

export interface Chain {
  id: number;
  slug: string;
  name: string;
  steps: string[];
  enabled: boolean;
}

export interface RequestRow {
  id: number;
  ts: string;
  account: string | null;
  client: string;
  method: string;
  path: string;
  status: number;
  latency_ms: number;
  cached: number;
  error: string | null;
  provider_slug?: string | null;
}

export interface Tunables {
  strategy: string;
  max_retries: number;
  quota_reserve: number;
  default_quota_limit: number;
  cooldown_base_seconds: number;
  cooldown_max_seconds: number;
  refund_on: string[];
  upstream_timeout: number;
}

export interface Status {
  version: string;
  period: string;
  resets_at: string;
  resets_in_seconds: number;
  accounts_total: number;
  accounts_usable: number;
  accounts_invalid: number;
  accounts_disabled: number;
  accounts_on_cooldown: number;
  quota_limit_total: number;
  quota_used_total: number;
  quota_remaining_total: number;
  quota_available_total: number;
  requests_ok: number;
  requests_failed: number;
  requests_refunded: number;
  in_flight: number;
  can_serve: boolean;
  auth_enabled: boolean;
  dashboard_public: boolean;
  uptime_seconds: number;
  counters: Record<string, number>;
  cache: Record<string, number | boolean>;
  accounts: Account[];
  recent: RequestRow[];
  providers: Provider[];
  chains: Chain[];
  default_route: string;
  tunables: Tunables;
  upstream: string;
}

export interface Preset {
  name: string;
  base_url: string;
  auth_style: string;
  auth_header_name?: string;
  auth_param_name?: string;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

const KEY = 'serpent_key';

export function getKey(): string {
  try {
    return sessionStorage.getItem(KEY) ?? '';
  } catch {
    return '';
  }
}

export function setKey(value: string): void {
  try {
    if (value) sessionStorage.setItem(KEY, value);
    else sessionStorage.removeItem(KEY);
  } catch {
    /* storage can be unavailable (private mode); the key just won't persist */
  }
}

export function authHeaders(key = getKey()): Record<string, string> {
  return key ? { 'X-Router-Key': key } : {};
}

export async function errorMessage(res: Response): Promise<string> {
  try {
    const data = await res.clone().json();
    if (data && typeof data.error === 'string') return data.error;
    if (data && typeof data.detail === 'string') return data.detail;
  } catch {
    /* not JSON */
  }
  return `${res.status} ${res.statusText || 'request failed'}`.trim();
}

export async function api<T = unknown>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: {
      ...authHeaders(),
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new ApiError(res.status, await errorMessage(res));
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const get = <T>(path: string) => api<T>('GET', path);
export const post = <T>(path: string, body?: unknown) => api<T>('POST', path, body ?? {});
export const patch = <T>(path: string, body: unknown) => api<T>('PATCH', path, body);
export const put = <T>(path: string, body: unknown) => api<T>('PUT', path, body);
export const del = (path: string) => api<void>('DELETE', path);

/** Work out what the current key may do. */
export async function detectRole(key = getKey()): Promise<Role> {
  const h = authHeaders(key);
  const a = await fetch('/admin/config', { headers: h });
  if (a.ok) return 'admin';
  if (a.status === 403) {
    const r = await fetch('/v1/quota', { headers: h });
    return r.ok ? 'read' : 'none';
  }
  return 'none';
}

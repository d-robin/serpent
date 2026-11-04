export function pct(used: number, limit: number): number {
  if (!limit) return 0;
  return Math.max(0, Math.min(100, (100 * used) / limit));
}

export function duration(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d) return `${d}d ${h}h`;
  if (h) return `${h}h ${m}m`;
  if (m) return `${m}m ${s % 60}s`;
  return `${s}s`;
}

export function ago(iso: string | null, now = Date.now()): string {
  if (!iso) return '—';
  const t = Date.parse(iso.endsWith('Z') || /[+-]\d\d:\d\d$/.test(iso) ? iso : iso + 'Z');
  if (Number.isNaN(t)) return iso;
  const s = Math.round((now - t) / 1000);
  if (s < 5) return 'just now';
  if (s < 0) return 'soon';
  return `${duration(s)} ago`;
}

export function barClass(percent: number): '' | 'warn' | 'bad' {
  if (percent >= 90) return 'bad';
  if (percent >= 70) return 'warn';
  return '';
}

/** Public path a caller uses to reach a provider or chain. */
export function endpointFor(slug: string, isDefault = false, origin = ''): string {
  return isDefault ? `${origin}/v1/` : `${origin}/p/${slug}/`;
}

export function slugify(input: string): string {
  return input
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 32);
}

export function move<T>(list: T[], index: number, delta: number): T[] {
  const to = index + delta;
  if (to < 0 || to >= list.length) return list;
  const copy = [...list];
  [copy[index], copy[to]] = [copy[to], copy[index]];
  return copy;
}

// Turn an arbitrary search-API response into a plain list of results.
// The router does not know what any provider returns, so this looks for the first array
// of objects that have something title-like and something link-like.

export interface Hit {
  title: string;
  url: string;
  snippet: string;
  extra?: string;
}

const TITLE = ['title', 'name', 'headline'];
const LINK = ['link', 'url', 'href', 'product_link', 'link_clean', 'website'];
const TEXT = ['snippet', 'description', 'content', 'text', 'summary', 'body'];

function pick(o: Record<string, unknown>, keys: string[]): string {
  for (const k of keys) {
    const v = o[k];
    if (typeof v === 'string' && v.trim()) return v.trim();
  }
  return '';
}

/** Shop-style details, when present: price, rating, reviews. */
function extras(o: Record<string, unknown>): string | undefined {
  const bits: string[] = [];
  const price = o.price;
  if (typeof price === 'string' && price) bits.push(price);
  else if (typeof price === 'number') bits.push(String(price));
  if (typeof o.rating === 'number') bits.push(`${o.rating}★`);
  if (typeof o.reviews === 'number') bits.push(`${o.reviews.toLocaleString('en-US')} reviews`);
  if (typeof o.source === 'string' && o.source) bits.push(o.source);
  return bits.length ? bits.join(' · ') : undefined;
}

function asHits(arr: unknown[]): Hit[] {
  const hits: Hit[] = [];
  for (const item of arr) {
    if (!item || typeof item !== 'object') continue;
    const o = item as Record<string, unknown>;
    const title = pick(o, TITLE);
    const url = pick(o, LINK);
    if (title && url) hits.push({ title, url, snippet: pick(o, TEXT), extra: extras(o) });
  }
  return hits;
}

/** Breadth-first, so the main result list wins over nested ones. */
export function extractHits(data: unknown): Hit[] {
  const queue: unknown[] = [data];
  for (let seen = 0; queue.length && seen < 200; seen++) {
    const node = queue.shift();
    if (Array.isArray(node)) {
      const hits = asHits(node);
      if (hits.length) return hits;
      queue.push(...node);
    } else if (node && typeof node === 'object') {
      queue.push(...Object.values(node));
    }
  }
  return [];
}

export function host(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
}

/** Put the query into a request-body template; JSON strings are escaped properly. */
export function fillTemplate(template: string, query: string): string {
  return template.replaceAll('{query}', JSON.stringify(query).slice(1, -1));
}

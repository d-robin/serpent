// How to ask each known provider for a particular kind of search.
// `params` are fixed query parameters; `q` is the name of the parameter that carries
// the user's words (Amazon calls it `k`, nearly everyone else `q`).

export interface Kind {
  id: string;
  label: string;
  method: 'GET' | 'POST';
  path: string;
  params?: Record<string, string>;
  q: string;
}

const serpapi = (id: string, label: string, engine: string, q = 'q', extra: Record<string, string> = {}): Kind =>
  ({ id, label, method: 'GET', path: 'search', params: { engine, ...extra }, q });

export const KINDS: Record<string, Kind[]> = {
  serpapi: [
    serpapi('google', 'Google', 'google'),
    serpapi('amazon', 'Amazon', 'amazon', 'k'),
    serpapi('google_shopping', 'Google Shopping', 'google_shopping'),
    serpapi('google_news', 'Google News', 'google_news'),
    serpapi('google_images', 'Google Images', 'google_images'),
    serpapi('google_maps', 'Google Maps', 'google_maps', 'q', { type: 'search' }),
  ],
};

export function buildPath(kind: Kind, query: string): string {
  const sp = new URLSearchParams({ ...(kind.params ?? {}), [kind.q]: query });
  return `${kind.path}?${sp.toString()}`;
}

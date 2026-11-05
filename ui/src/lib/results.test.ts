import { describe, expect, it } from 'vitest';
import { KINDS, buildPath } from './engines';
import { extractHits, fillTemplate, host } from './results';

describe('extractHits', () => {
  it('finds results under any key', () => {
    const data = { meta: 1, organic: [{ title: 'A', link: 'https://a.com/x', snippet: 's' }, { nope: 1 }] };
    expect(extractHits(data)).toEqual([{ title: 'A', url: 'https://a.com/x', snippet: 's', extra: undefined }]);
  });
  it('accepts other field names and nesting', () => {
    const data = { web: { results: [{ name: 'B', url: 'https://b.org', description: 'd' }] } };
    expect(extractHits(data)[0]).toMatchObject({ title: 'B', url: 'https://b.org', snippet: 'd' });
  });
  it('returns nothing for unknown shapes', () => {
    expect(extractHits({ a: [1, 2], b: 'x' })).toEqual([]);
    expect(extractHits(null)).toEqual([]);
  });
});

describe('shop results', () => {
  it('keeps price and rating', () => {
    const data = { organic_results: [{ title: 'Kettle', link_clean: 'https://amazon.com/dp/1', price: '$24.99', rating: 4.5, reviews: 1200 }] };
    expect(extractHits(data)[0].extra).toBe('$24.99 · 4.5★ · 1,200 reviews');
  });
});

describe('engines', () => {
  it('builds a SerpApi Amazon path with k=', () => {
    const k = KINDS.serpapi.find((x) => x.id === 'amazon')!;
    expect(buildPath(k, 'air fryer')).toBe('search?engine=amazon&k=air+fryer');
  });
  it('builds a Google path', () => {
    expect(buildPath(KINDS.serpapi[0], 'a&b')).toBe('search?engine=google&q=a%26b');
  });
});

describe('helpers', () => {
  it('host drops www', () => expect(host('https://www.example.com/a')).toBe('example.com'));
  it('fillTemplate escapes quotes', () => {
    const body = fillTemplate('{"q":"{query}"}', 'say "hi"');
    expect(JSON.parse(body)).toEqual({ q: 'say "hi"' });
  });
});

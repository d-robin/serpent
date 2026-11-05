import { describe, expect, it } from 'vitest';
import { extractHits, fillTemplate, host } from './results';

describe('extractHits', () => {
  it('finds results under any key', () => {
    const data = { meta: 1, organic: [{ title: 'A', link: 'https://a.com/x', snippet: 's' }, { nope: 1 }] };
    expect(extractHits(data)).toEqual([{ title: 'A', url: 'https://a.com/x', snippet: 's' }]);
  });
  it('accepts other field names and nesting', () => {
    const data = { web: { results: [{ name: 'B', url: 'https://b.org', description: 'd' }] } };
    expect(extractHits(data)[0]).toEqual({ title: 'B', url: 'https://b.org', snippet: 'd' });
  });
  it('returns nothing for unknown shapes', () => {
    expect(extractHits({ a: [1, 2], b: 'x' })).toEqual([]);
    expect(extractHits(null)).toEqual([]);
  });
});

describe('helpers', () => {
  it('host drops www', () => expect(host('https://www.example.com/a')).toBe('example.com'));
  it('fillTemplate escapes quotes', () => {
    const body = fillTemplate('{"q":"{query}"}', 'say "hi"');
    expect(JSON.parse(body)).toEqual({ q: 'say "hi"' });
  });
});

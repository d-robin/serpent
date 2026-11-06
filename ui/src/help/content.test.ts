import { describe, expect, it } from 'vitest';
import { DOCS, inline, plain, sections, type Ctx } from './content';

const ctx = (over: Partial<Ctx> = {}): Ctx => ({
  origin: 'http://127.0.0.1:8971', defaultRoute: 'serpapi', slug: 'serpapi', preset: 'serpapi', hasProvider: true, ...over,
});

describe('help content', () => {
  it('has the sections people need, with unique ids', () => {
    const all = sections(ctx());
    const ids = all.map((s) => s.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const need of ['start', 'connect', 'agents', 'how', 'deploy', 'logs', 'troubleshoot', 'move', 'uninstall', 'keys']) {
      expect(ids).toContain(need);
    }
    for (const s of all) expect(s.blocks.length).toBeGreaterThan(0);
  });

  it('keeps every table rectangular and every snippet non-empty', () => {
    for (const s of sections(ctx())) for (const b of s.blocks) {
      if (b.t === 'table') for (const r of b.rows) expect(r.length, `${s.id}: ${r[0]}`).toBe(b.head.length);
      if (b.t === 'code') expect(b.text.trim().length).toBeGreaterThan(0);
    }
  });

  it('fills examples from the live setup', () => {
    const txt = (c: Ctx) => sections(c).map(plain).join(' ');
    expect(txt(ctx())).toContain('http://127.0.0.1:8971/p/serpapi/search?engine=google');
    const serper = txt(ctx({ preset: 'serper', slug: 'serper' }));
    expect(serper).toContain('curl -x post');            // Serper is POST with a JSON body
    expect(serper).toContain('http://127.0.0.1:8971/p/serper/search');
    expect(txt(ctx({ hasProvider: false, slug: 'provider', preset: '' }))).toContain('add a provider first');
  });

  it('never tells people to put a key in a URL or share one', () => {
    const everything = sections(ctx()).map(plain).join(' ');
    expect(everything).not.toMatch(/api_key=[a-z0-9]{6,}/);
    expect(everything).toContain('never in source code');
  });

  it('links to the repository docs over https', () => {
    expect(DOCS.startsWith('https://')).toBe(true);
  });
});

describe('inline markup', () => {
  it('escapes HTML before formatting, so nothing injected survives', () => {
    expect(inline('<img src=x onerror=1> `a<b`')).toBe('&lt;img src=x onerror=1&gt; <code>a&lt;b</code>');
  });
  it('renders bold, code and https links only', () => {
    expect(inline('**x** [d](https://e.com/p) [bad](javascript:alert(1))')).toBe(
      '<strong>x</strong> <a href="https://e.com/p" target="_blank" rel="noopener noreferrer">d</a> [bad](javascript:alert(1))');
  });
});

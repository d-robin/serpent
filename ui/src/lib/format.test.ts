import { describe, expect, it } from 'vitest';
import { ago, barClass, duration, endpointFor, move, pct, slugify } from './format';

describe('format helpers', () => {
  it('computes bounded percentages', () => {
    expect(pct(50, 200)).toBe(25);
    expect(pct(5, 0)).toBe(0);
    expect(pct(300, 200)).toBe(100);
  });
  it('formats durations compactly', () => {
    expect(duration(45)).toBe('45s');
    expect(duration(125)).toBe('2m 5s');
    expect(duration(3 * 3600 + 120)).toBe('3h 2m');
    expect(duration(26 * 86400 + 5 * 3600)).toBe('26d 5h');
  });
  it('treats naive timestamps as UTC', () => {
    const now = Date.parse('2026-11-04T12:10:00Z');
    expect(ago('2026-11-04T12:00:00', now)).toBe('10m 0s ago');
    expect(ago(null)).toBe('—');
  });
  it('picks bar severity', () => {
    expect([barClass(10), barClass(75), barClass(95)]).toEqual(['', 'warn', 'bad']);
  });
  it('builds endpoints', () => {
    expect(endpointFor('serper')).toBe('/p/serper/');
    expect(endpointFor('serper', true)).toBe('/v1/');
  });
  it('slugifies', () => {
    expect(slugify(' My Provider!! ')).toBe('my-provider');
    expect(slugify('a'.repeat(50))).toHaveLength(32);
  });
  it('moves list items without mutating or overflowing', () => {
    const l = ['a', 'b', 'c'];
    expect(move(l, 0, 1)).toEqual(['b', 'a', 'c']);
    expect(move(l, 0, -1)).toBe(l);
    expect(l).toEqual(['a', 'b', 'c']);
  });
});

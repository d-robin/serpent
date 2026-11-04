import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import Bar from './Bar.svelte';

describe('Bar', () => {
  it('exposes progress semantics and severity class', () => {
    render(Bar, { used: 95, limit: 100, label: 'acct' });
    const bar = screen.getByRole('progressbar', { name: 'acct' });
    expect(bar.getAttribute('aria-valuenow')).toBe('95');
    expect(bar.className).toContain('bad');
  });
});

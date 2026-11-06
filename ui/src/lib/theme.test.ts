import { beforeEach, describe, expect, it } from 'vitest';
import { theme } from './theme.svelte';

describe('theme', () => {
  beforeEach(() => { localStorage.clear(); theme.set('light'); });

  it('is light by default and ignores the system setting', () => {
    expect(theme.mode).toBe('light');
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
  });

  it('toggles to dark and back, writing the attribute the CSS reads', () => {
    theme.toggle();
    expect(theme.mode).toBe('dark');
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    theme.toggle();
    expect(theme.mode).toBe('light');
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
  });

  it('remembers dark only', () => {
    theme.set('dark');
    expect(localStorage.getItem('serpent_theme')).toBe('dark');
    theme.set('light');
    expect(localStorage.getItem('serpent_theme')).toBeNull();
  });
});

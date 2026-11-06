import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import Dialog from './Dialog.svelte';
import { store } from './store.svelte';

describe('in-app confirmation', () => {
  it('resolves true on confirm and false on cancel, and clears itself', async () => {
    const yes = store.ask('Delete main?', 'Its key is removed.', 'Delete', true);
    render(Dialog);
    expect(screen.getByRole('alertdialog', { name: 'Delete main?' })).toBeTruthy();
    screen.getByRole('button', { name: 'Delete' }).click();
    expect(await yes).toBe(true);
    expect(store.dialog).toBeNull();

    const no = store.ask('Reset?');
    store.dialog!.resolve(false);
    expect(await no).toBe(false);
  });
});

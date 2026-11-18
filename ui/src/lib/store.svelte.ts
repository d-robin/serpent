import {
  ApiError, detectRole, get, getKey, post, setKey, type Preset, type ProviderUsage, type Role, type Status,
} from './api';

class Store {
  status = $state<Status | null>(null);
  presets = $state<Record<string, Preset>>({});
  strategies = $state<string[]>([]);
  role = $state<Role>('none');
  key = $state(getKey());
  hints = $state<Record<number, string>>({});
  loading = $state(true);
  error = $state('');
  /** A one-shot request from the palette to a page (e.g. open its add form). */
  intent = $state('');
  toasts = $state<{ id: number; text: string; bad: boolean }[]>([]);
  dialog = $state<{ title: string; body: string; label: string; danger: boolean; resolve: (ok: boolean) => void } | null>(null);
  /** What each provider says about each key (cached; filled on demand by lookup()). */
  usage = $state<Record<number, ProviderUsage | 'loading'>>({});
  private timer: ReturnType<typeof setInterval> | undefined;
  private nextToast = 1;

  get isAdmin() { return this.role === 'admin'; }
  get needsLogin() { return this.role === 'none' && !!this.error; }

  async connect(key = this.key) {
    this.key = key;
    setKey(key);
    this.loading = true;
    try {
      this.role = await detectRole(key);
      if (this.role === 'none' && key) {
        this.key = '';
        setKey('');
      }
      await this.refresh();
      if (this.role === 'admin') {
        try {
          const p = await get<{ presets: Record<string, Preset>; strategies: string[] }>('/admin/presets');
          this.presets = p.presets;
          this.strategies = p.strategies;
        } catch { /* presets are a convenience */ }
      }
    } finally {
      this.loading = false;
    }
    clearInterval(this.timer);
    this.timer = setInterval(() => void this.refresh(), 5000);
  }

  async refresh() {
    try {
      this.status = await get<Status>('/api/status');
      if (this.role === 'admin') {
        try {
          const r = await get<{ accounts: { id: number; key_hint: string }[] }>('/admin/accounts');
          this.hints = Object.fromEntries(r.accounts.map((a) => [a.id, a.key_hint]));
        } catch { /* hints are cosmetic */ }
      }
      this.error = '';
      if (this.role === 'none' && this.status && !this.status.auth_enabled) this.role = 'admin';
    } catch (e) {
      this.error = e instanceof ApiError ? e.message : 'cannot reach the server';
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) this.status = null;
    }
  }

  logout() {
    this.key = '';
    setKey('');
    this.role = 'none';
    this.status = null;
    this.error = 'Enter a router key to continue.';
  }

  toast(text: string, bad = false) {
    const id = this.nextToast++;
    this.toasts = [...this.toasts, { id, text, bad }];
    setTimeout(() => { this.toasts = this.toasts.filter((t) => t.id !== id); }, bad ? 6000 : 3000);
  }

  /** Ask the provider about one account (free call, not counted as usage). */
  async lookup(id: number) {
    this.usage[id] = 'loading';
    try { this.usage[id] = await get<ProviderUsage>(`/admin/accounts/${id}/provider-usage`); }
    catch (e) { this.usage[id] = { supported: true, error: e instanceof Error ? e.message : 'lookup failed' }; }
  }

  /** Raise Serpent's counts to what the providers say they served (never lowers a count). */
  async syncUsage(): Promise<boolean> {
    try {
      const r = await post<{ changed: number; accounts: { error?: string }[] }>('/admin/accounts/sync-usage');
      const failed = r.accounts.filter((a) => a.error).length;
      this.toast(r.changed ? `Matched ${r.changed} account${r.changed === 1 ? '' : 's'} to the provider`
        : failed ? 'Could not reach the provider for some accounts' : 'Already in step with the provider', failed > 0 && !r.changed);
      await this.refresh();
      return true;
    } catch (e) {
      this.toast(e instanceof Error ? e.message : 'sync failed', true);
      return false;
    }
  }

  /** An in-app confirmation (never the browser's own box). Resolves true when confirmed. */
  ask(title: string, body = '', label = 'Confirm', danger = false): Promise<boolean> {
    return new Promise((resolve) => {
      this.dialog = { title, body, label, danger, resolve: (ok) => { this.dialog = null; resolve(ok); } };
    });
  }

  /** Run a mutation, toast the outcome, refresh. Returns true on success. */
  async act(fn: () => Promise<unknown>, ok: string): Promise<boolean> {
    try {
      await fn();
      this.toast(ok);
      await this.refresh();
      return true;
    } catch (e) {
      this.toast(e instanceof Error ? e.message : 'failed', true);
      return false;
    }
  }
}

export const store = new Store();

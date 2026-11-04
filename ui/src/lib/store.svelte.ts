import {
  ApiError, detectRole, get, getKey, setKey, type Preset, type Role, type Status,
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
  toasts = $state<{ id: number; text: string; bad: boolean }[]>([]);
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

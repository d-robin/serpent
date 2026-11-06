export type Mode = 'light' | 'dark';
const KEY = 'serpent_theme';

/** Light unless someone chose dark. The system setting is deliberately not consulted. */
function read(): Mode {
  try { return localStorage.getItem(KEY) === 'dark' ? 'dark' : 'light'; } catch { return 'light'; }
}

class Theme {
  mode = $state<Mode>(read());

  apply() {
    const root = document.documentElement;
    if (this.mode === 'dark') root.setAttribute('data-theme', 'dark');
    else root.removeAttribute('data-theme');
  }

  set(mode: Mode) {
    this.mode = mode;
    try { mode === 'dark' ? localStorage.setItem(KEY, 'dark') : localStorage.removeItem(KEY); } catch { /* private mode */ }
    this.apply();
  }

  toggle() { this.set(this.mode === 'dark' ? 'light' : 'dark'); }
}

export const theme = new Theme();

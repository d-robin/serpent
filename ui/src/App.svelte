<script lang="ts">
  import { onMount } from 'svelte';
  import { setKey } from './lib/api';
  import Dialog from './lib/Dialog.svelte';
  import Icon from './lib/Icon.svelte';
  import Logo from './lib/Logo.svelte';
  import Palette from './lib/Palette.svelte';
  import type { PaletteItem } from './lib/palette';
  import { store } from './lib/store.svelte';
  import { theme } from './lib/theme.svelte';
  import Accounts from './pages/Accounts.svelte';
  import Chains from './pages/Chains.svelte';
  import Help from './pages/Help.svelte';
  import Integrate from './pages/Integrate.svelte';
  import Overview from './pages/Overview.svelte';
  import Providers from './pages/Providers.svelte';
  import Requests from './pages/Requests.svelte';
  import Search from './pages/Search.svelte';
  import Settings from './pages/Settings.svelte';
  import TryIt from './pages/TryIt.svelte';

  type NavItem = [string, string, string, string];
  const nav: { group: string; items: NavItem[] }[] = [
    { group: 'Operate', items: [['overview', 'Overview', 'overview', 'o'], ['search', 'Search', 'search', 's'], ['requests', 'Requests', 'requests', 'r']] },
    { group: 'Configure', items: [['providers', 'Providers', 'providers', 'p'], ['accounts', 'Accounts', 'accounts', 'a'], ['chains', 'Chains', 'chains', 'c']] },
    { group: 'Build', items: [['integrate', 'Integrate', 'integrate', 'i'], ['try', 'Raw request', 'raw', 'w'], ['settings', 'Settings', 'settings', 'e']] },
    { group: 'Support', items: [['help', 'Help', 'help', 'h']] },
  ];
  const pages: NavItem[] = nav.flatMap((g) => g.items);

  const mod = /Mac|iPhone|iPad/.test(navigator.platform) ? '⌘' : 'Ctrl ';
  let route = $state(location.hash.slice(2).split('?')[0] || 'overview');
  let draft = $state('');
  let askLogin = $state(false);
  let navOpen = $state(false);
  let palette = $state(false);

  function go(id: string) { location.hash = `#/${id}`; navOpen = false; }

  // `serpent up` opens /ui/#key=<admin key>: take the key, then scrub it from the address bar.
  function adoptKeyFromHash(): boolean {
    const m = /^#key=(.+)$/.exec(location.hash);
    if (!m) return false;
    store.key = decodeURIComponent(m[1]);
    setKey(store.key);
    history.replaceState(null, '', location.pathname + location.search + '#/overview');
    route = 'overview';
    return true;
  }

  let pendingG = 0;
  function keydown(e: KeyboardEvent) {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); palette = !palette; return; }
    const t = e.target as HTMLElement | null;
    if (t?.closest?.('input, textarea, select, [contenteditable]') || e.metaKey || e.ctrlKey || e.altKey || !store.status) return;
    if (pendingG && Date.now() - pendingG < 1100) {
      pendingG = 0;
      const hit = pages.find((p) => p[3] === e.key);
      if (hit) { e.preventDefault(); go(hit[0]); }
      return;
    }
    if (e.key === 'g') pendingG = Date.now();
    else if (e.key === '/') { e.preventDefault(); go('search'); }
  }

  onMount(() => {
    theme.apply();
    const adopted = adoptKeyFromHash();
    const onHash = () => {
      if (adoptKeyFromHash()) { void store.connect(); return; }
      route = location.hash.slice(2).split('?')[0] || 'overview';
    };
    addEventListener('hashchange', onHash);
    void store.connect(adopted ? store.key : undefined);
    return () => removeEventListener('hashchange', onHash);
  });

  async function login(e: SubmitEvent) {
    e.preventDefault();
    await store.connect(draft.trim());
    if (store.role !== 'none') { askLogin = false; draft = ''; }
    else store.error = 'That key was not accepted.';
  }

  const roleLabel = $derived(store.role === 'admin' ? 'Admin' : store.role === 'read' ? 'Read-only' : 'Public view');
  const themeLabel = $derived(theme.mode === 'dark' ? 'Switch to the light theme' : 'Switch to the dark theme');
  const items = $derived<PaletteItem[]>([
    ...pages.map(([id, label, icon, k]) => ({ group: 'Go to', label, icon, hint: `g ${k}`, run: () => go(id) })),
    ...(store.isAdmin ? [
      { group: 'Actions', label: 'Add a provider', icon: 'plus', run: () => { store.intent = 'add-provider'; go('providers'); } },
      { group: 'Actions', label: 'Add an account', icon: 'plus', run: () => { store.intent = 'add-account'; go('accounts'); } },
      { group: 'Actions', label: 'New chain', icon: 'plus', run: () => { store.intent = 'add-chain'; go('chains'); } },
    ] : []),
    { group: 'Actions', label: 'Copy the API contract address', icon: 'copy', run: () => { void navigator.clipboard?.writeText(`${location.origin}/v1/contract`); store.toast('Contract address copied'); } },
    { group: 'Appearance', label: themeLabel, icon: theme.mode === 'dark' ? 'sun' : 'moon', run: () => theme.toggle() },
    ...(store.status?.auth_enabled ? [store.role === 'none' || store.role === 'read'
      ? { group: 'Session', label: 'Sign in', icon: 'key', run: () => { askLogin = true; store.error = ''; } }
      : { group: 'Session', label: 'Sign out', icon: 'exit', run: () => store.logout() }] : []),
  ]);
</script>

<svelte:window onkeydown={keydown} />

{#if store.status === null && store.loading && !askLogin}
  <div class="gate" style="grid-template-columns:1fr"><div class="formside"><Logo size={44} /></div></div>
{:else if store.status === null || askLogin}
  <div class="gate">
    <div class="brandside">
      <div class="brand"><Logo size={30} /><span class="word">Serpent</span></div>
      <h1>One key in front. <em>Many accounts behind.</em></h1>
      <span class="faint">Snake Charmer, the control room for your search router.</span>
    </div>
    <div class="formside">
      <form onsubmit={login}>
        <div><h2>Sign in</h2>
          <p class="muted" style="margin-top:8px">Use an <code>admin</code> key to manage providers and accounts, or a <code>read</code> key to look around.</p></div>
        {#if store.error}<div class="note bad" role="alert"><Icon name="alert" /><span>{store.error}</span></div>{/if}
        <label class="field">Router key
          <input type="password" class="mono-input" autocomplete="off" bind:value={draft} required placeholder="rk-…" />
          <span class="hint">It is in your <code>.env</code> file, or run <code>serpent keys</code>.</span></label>
        <div class="row">
          <button class="btn primary" disabled={store.loading}>{store.loading ? 'Checking…' : 'Continue'}</button>
          {#if askLogin}<button type="button" class="btn ghost" onclick={() => (askLogin = false)}>Back</button>{/if}
        </div>
      </form>
    </div>
  </div>
{:else}
  <div class="app">
    <header class="topbar">
      <button class="btn ghost icon" onclick={() => (navOpen = true)} aria-label="Open menu"><Icon name="menu" /></button>
      <Logo size={24} /><span class="word">Serpent</span><span class="grow"></span>
      <button class="btn ghost icon" onclick={() => (palette = true)} aria-label="Command palette"><Icon name="search" /></button>
    </header>

    {#if navOpen}<div class="scrim" style="z-index:61" onclick={() => (navOpen = false)} role="presentation"></div>{/if}
    <aside class="side" class:open={navOpen} aria-label="Primary">
      <a class="brand" href="#/overview" onclick={() => (navOpen = false)}>
        <Logo size={30} /><span><span class="word">Serpent</span><span class="sub">Snake Charmer</span></span>
      </a>
      <button class="jump" onclick={() => { palette = true; navOpen = false; }}><Icon name="search" size={14} /><span>Jump to…</span><kbd>{mod}K</kbd></button>
      <nav class="nav">
        {#each nav as g}
          <h4>{g.group}</h4>
          {#each g.items as [id, label, icon]}
            <a href="#/{id}" aria-current={route === id ? 'page' : undefined} onclick={() => (navOpen = false)}>
              <Icon name={icon} />{label}
              {#if id === 'providers'}<span class="tag">{store.status.providers.length}</span>{/if}
              {#if id === 'accounts'}<span class="tag">{store.status.accounts_total}</span>{/if}
            </a>
          {/each}
        {/each}
      </nav>
      <div class="side-foot">
        <div class="status-line">
          <span class="dot {store.status.can_serve ? 'ok live' : 'bad'}"></span>
          {store.status.can_serve ? 'Serving' : 'No capacity'}<span class="faint" style="margin-left:2px">v{store.status.version}</span>
        </div>
        <div class="who">
          <span class="grow">{roleLabel}</span>
          <button class="btn ghost icon sm" onclick={() => theme.toggle()} aria-label={themeLabel} title={themeLabel}>
            <Icon name={theme.mode === 'dark' ? 'sun' : 'moon'} size={15} /></button>
          {#if store.status.auth_enabled}
            {#if store.role === 'admin'}
              <button class="btn ghost icon sm" onclick={() => store.logout()} aria-label="Sign out" title="Sign out"><Icon name="exit" size={15} /></button>
            {:else}
              <button class="btn ghost icon sm" onclick={() => { askLogin = true; store.error = ''; }} aria-label="Sign in" title="Sign in"><Icon name="key" size={15} /></button>
            {/if}
          {/if}
        </div>
      </div>
    </aside>

    <main class="main">
      {#key route}
        <div class="page">
          {#if !store.status.auth_enabled}
            <div class="note warn" style="margin-bottom:28px"><Icon name="alert" /><span>
              Authentication is <strong>off</strong> (<code>ROUTER_KEYS</code> is empty). Anyone who can reach this port can manage it.</span></div>
          {/if}
          {#if route === 'providers'}<Providers />
          {:else if route === 'accounts'}<Accounts />
          {:else if route === 'chains'}<Chains />
          {:else if route === 'settings'}<Settings />
          {:else if route === 'integrate'}<Integrate />
          {:else if route === 'requests'}<Requests />
          {:else if route === 'search'}<Search />
          {:else if route === 'try'}<TryIt />
          {:else if route === 'help'}<Help />
          {:else}<Overview />{/if}
        </div>
      {/key}
    </main>
  </div>
  {#if palette}<Palette {items} onclose={() => (palette = false)} />{/if}
{/if}

{#if store.dialog}<Dialog />{/if}

<div class="toasts" aria-live="polite">
  {#each store.toasts as t (t.id)}<div class="toast" class:bad={t.bad} role="status"><Icon name={t.bad ? 'alert' : 'check'} />{t.text}</div>{/each}
</div>

<script lang="ts">
  import { onMount } from 'svelte';
  import { setKey } from './lib/api';
  import { store } from './lib/store.svelte';
  import Overview from './pages/Overview.svelte';
  import Providers from './pages/Providers.svelte';
  import Accounts from './pages/Accounts.svelte';
  import Chains from './pages/Chains.svelte';
  import Settings from './pages/Settings.svelte';
  import Search from './pages/Search.svelte';
  import TryIt from './pages/TryIt.svelte';

  const tabs = [
    ['overview', 'Overview'], ['search', 'Search'], ['providers', 'Providers'], ['accounts', 'Accounts'],
    ['chains', 'Chains'], ['settings', 'Settings'], ['try', 'Raw request'],
  ] as const;

  let route = $state(location.hash.slice(2) || 'overview');
  let draft = $state('');
  let askLogin = $state(false);

  // `serpent up` opens /ui/#key=<admin key>: take the key, then scrub it from the address bar.
  function adoptKeyFromHash() {
    const m = /^#key=(.+)$/.exec(location.hash);
    if (!m) return;
    store.key = decodeURIComponent(m[1]);
    setKey(store.key);
    history.replaceState(null, '', location.pathname + location.search + '#/overview');
    route = 'overview';
  }

  onMount(() => {
    adoptKeyFromHash();
    const onHash = () => (route = location.hash.slice(2) || 'overview');
    addEventListener('hashchange', onHash);
    void store.connect();
    return () => removeEventListener('hashchange', onHash);
  });

  async function login(e: SubmitEvent) {
    e.preventDefault();
    await store.connect(draft.trim());
    if (store.role !== 'none') {
      askLogin = false;
      draft = '';
    } else {
      store.error = 'That key was not accepted.';
    }
  }
  const roleLabel = $derived(store.role === 'admin' ? 'admin' : store.role === 'read' ? 'read-only' : 'public view');
</script>

<div class="shell">
  <header class="top">
    <a class="brand" href="#/overview">
      <img src="/ui/logo.svg" alt="" />
      <span>Snake Charmer <small>for Serpent{store.status ? ` v${store.status.version}` : ''}</small></span>
    </a>
    <span class="spacer"></span>
    {#if store.status}
      <span class="muted" title="router health">
        <span class="dot" class:off={!store.status.can_serve}></span>{store.status.can_serve ? 'serving' : 'no capacity'}
      </span>
      <span class="pill {store.isAdmin ? 'accent' : 'off'}">{roleLabel}</span>
      {#if store.status.auth_enabled}
        {#if store.role === 'admin'}
          <button class="tiny" onclick={() => store.logout()}>Sign out</button>
        {:else}
          <button class="tiny" onclick={() => { askLogin = true; store.error = ''; }}>Sign in</button>
        {/if}
      {/if}
    {/if}
  </header>

  {#if store.status === null || askLogin}
    <div class="login card stack">
      <img src="/ui/logo.svg" alt="" />
      <h2>Sign in</h2>
      <p class="muted" style="margin:0">
        Use an <code>admin</code> key to manage providers and accounts, or a <code>read</code> key to look around.
      </p>
      {#if store.error}<div class="banner bad" role="alert">{store.error}</div>{/if}
      <form class="stack" onsubmit={login}>
        <label class="field">Router key
          <input type="password" autocomplete="off" bind:value={draft} required />
        </label>
        <div class="actions" style="justify-content:flex-start">
          <button class="primary" disabled={store.loading}>{store.loading ? 'Checking…' : 'Continue'}</button>
          {#if askLogin}<button type="button" onclick={() => (askLogin = false)}>Back</button>{/if}
        </div>
      </form>
    </div>
  {:else}
    <nav class="tabs" aria-label="Sections">
      {#each tabs as [id, label]}
        <a href="#/{id}" aria-current={route === id ? 'page' : undefined}>{label}</a>
      {/each}
    </nav>
    {#if !store.status.auth_enabled}
      <div class="banner warn" style="margin-bottom:16px">
        Authentication is <strong>off</strong> (<code>ROUTER_KEYS</code> is empty). Anyone who can reach this port can manage it.
      </div>
    {/if}
    <main>
      {#if route === 'providers'}<Providers />
      {:else if route === 'accounts'}<Accounts />
      {:else if route === 'chains'}<Chains />
      {:else if route === 'settings'}<Settings />
      {:else if route === 'search'}<Search />
      {:else if route === 'try'}<TryIt />
      {:else}<Overview />{/if}
    </main>
  {/if}
</div>

<div class="toasts" aria-live="polite">
  {#each store.toasts as t (t.id)}<div class="toast" class:bad={t.bad} role="status">{t.text}</div>{/each}
</div>

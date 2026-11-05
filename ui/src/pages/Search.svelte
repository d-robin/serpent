<script lang="ts">
  import { authHeaders } from '../lib/api';
  import { store } from '../lib/store.svelte';
  import { extractHits, fillTemplate, host, type Hit } from '../lib/results';

  const s = $derived(store.status!);
  const routes = $derived([
    { value: '/v1/', label: `Default (${s.default_route || 'none yet'})` },
    ...s.providers.map((p) => ({ value: `/p/${p.slug}/`, label: p.name || p.slug })),
    ...s.chains.map((c) => ({ value: `/p/${c.slug}/`, label: `${c.name || c.slug} (chain)` })),
  ]);

  const SAVED = 'serpent.search.options';
  function load() {
    try { return JSON.parse(localStorage.getItem(SAVED) ?? '{}'); } catch { return {}; }
  }
  const saved = load();
  let base = $state<string>(saved.base ?? '/v1/');
  let method = $state<string>(saved.method ?? 'POST');
  let path = $state<string>(saved.path ?? 'search');
  let template = $state<string>(saved.template ?? '{"q":"{query}"}');
  let key = $state('');
  let query = $state('');
  let busy = $state(false);
  let error = $state('');
  let hits = $state<Hit[]>([]);
  let raw = $state('');
  let showRaw = $state(false);
  let meta = $state<{ status: number; ms: number; via: string } | null>(null);
  let searched = $state(false);

  $effect(() => { if (!key) key = store.key; });
  $effect(() => {
    try { localStorage.setItem(SAVED, JSON.stringify({ base, method, path, template })); } catch { /* private mode */ }
  });

  const noProvider = $derived(s.providers.length === 0);
  const noAccount = $derived(!noProvider && s.accounts_total === 0);
  const needsKey = $derived(s.auth_enabled && !key);

  async function search(e: SubmitEvent) {
    e.preventDefault();
    const q = query.trim();
    if (!q) return;
    busy = true; error = ''; hits = []; raw = ''; meta = null; searched = true;
    const t0 = performance.now();
    try {
      let url = base + path.replace(/^\/+/, '');
      const init: RequestInit = { method, headers: { ...authHeaders(key) } };
      if (method === 'GET') {
        url += (url.includes('?') ? '&' : '?') + 'q=' + encodeURIComponent(q);
      } else {
        init.headers = { ...init.headers, 'Content-Type': 'application/json' };
        init.body = fillTemplate(template, q);
      }
      const res = await fetch(url, init);
      const text = await res.text();
      let data: unknown = null;
      try { data = JSON.parse(text); raw = JSON.stringify(data, null, 2); } catch { raw = text; }
      meta = {
        status: res.status,
        ms: Math.round(performance.now() - t0),
        via: res.headers.get('x-router-account') ?? res.headers.get('x-router-provider') ?? '',
      };
      if (!res.ok) {
        error = res.status === 401 ? 'The router needs a key. Sign in, or paste a client key under Options.'
          : res.status === 503 ? 'Nothing is set up to answer yet. Add a provider and an account first.'
          : `The search failed (HTTP ${res.status}). Open "Raw response" for details.`;
        showRaw = true;
      } else {
        hits = extractHits(data);
      }
      void store.refresh();
    } catch (err) {
      error = err instanceof Error ? err.message : 'request failed';
    } finally { busy = false; }
  }
</script>

<section class="stack search">
  <h2>Search</h2>

  {#if noProvider}
    <div class="banner warn">Nothing to search with yet. <a href="#/providers">Add a provider</a>, then an <a href="#/accounts">account</a> with its API key.</div>
  {:else if noAccount}
    <div class="banner warn">A provider is set up, but it has no API key yet. <a href="#/accounts">Add an account</a>.</div>
  {/if}

  <form class="searchbox" onsubmit={search} role="search">
    <input type="search" bind:value={query} placeholder="What do you want to look up?" aria-label="Search query"
           disabled={noProvider || noAccount} />
    <button class="primary" disabled={busy || !query.trim() || noProvider || noAccount}>{busy ? 'Searching…' : 'Search'}</button>
  </form>
  <p class="muted note">Each search is a real request and uses one credit from your quota.</p>

  <details class="card opts">
    <summary>Options</summary>
    <div class="form">
      <label class="field">Search with<select bind:value={base}>{#each routes as r}<option value={r.value}>{r.label}</option>{/each}</select></label>
      <label class="field">Client key
        <input type="password" autocomplete="off" bind:value={key} placeholder={s.auth_enabled ? 'client or admin key' : 'not required'} />
      </label>
      <label class="field">Method<select bind:value={method}>{#each ['POST', 'GET'] as m}<option>{m}</option>{/each}</select></label>
      <label class="field">Path<input bind:value={path} placeholder="search" /></label>
      {#if method === 'POST'}
        <label class="field wide">Request body, <code>{'{query}'}</code> is replaced by your search
          <textarea rows="2" bind:value={template} style="font-family:var(--mono)"></textarea>
        </label>
      {:else}
        <p class="muted wide" style="margin:0">Your search is sent as <code>?q=…</code>.</p>
      {/if}
      <p class="muted wide" style="margin:0">Providers differ in what they expect. Set this once to match yours; it is remembered in this browser.</p>
    </div>
  </details>

  {#if needsKey}<div class="banner warn">This router needs a key. Sign in (top right) or add a client key under Options.</div>{/if}
  {#if error}<div class="banner bad" role="alert">{error}</div>{/if}

  <div aria-live="polite" class="stack">
    {#if meta && !error}
      <p class="muted note">
        {hits.length ? `${hits.length} result${hits.length === 1 ? '' : 's'}` : 'No results to show'} · {meta.ms} ms{meta.via ? ` · via ${meta.via}` : ''}
      </p>
    {/if}
    {#each hits as h}
      <article class="hit">
        <span class="muted host">{host(h.url)}</span>
        <a class="title" href={h.url} target="_blank" rel="noopener noreferrer">{h.title}</a>
        {#if h.snippet}<p>{h.snippet}</p>{/if}
      </article>
    {/each}
    {#if searched && !busy && !error && meta && !hits.length}
      <p class="muted">The reply did not look like a list of results. Open "Raw response" to see what came back.</p>
    {/if}
  </div>

  {#if raw}
    <details bind:open={showRaw}>
      <summary class="muted">Raw response{meta ? ` (HTTP ${meta.status})` : ''}</summary>
      <pre class="out">{raw}</pre>
    </details>
  {/if}
</section>

<style>
  .search { max-width: 760px; }
  .searchbox { display: flex; gap: 8px; }
  .searchbox input { flex: 1; font-size: 17px; padding: 12px 14px; }
  .searchbox button { padding: 0 22px; }
  .note { margin: 0; font-size: 13px; }
  .opts summary { cursor: pointer; }
  .opts .form { margin-top: 12px; }
  .hit { padding: 12px 0; border-bottom: 1px solid var(--line); }
  .hit .host { font-size: 12px; display: block; }
  .hit .title { font-size: 17px; font-weight: 600; }
  .hit p { margin: 4px 0 0; color: var(--dim); }
</style>

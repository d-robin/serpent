<script lang="ts">
  import { onMount } from 'svelte';
  import { authHeaders } from '../lib/api';
  import { KINDS, buildPath, type Kind } from '../lib/engines';
  import Icon from '../lib/Icon.svelte';
  import PageHead from '../lib/PageHead.svelte';
  import { extractHits, fillTemplate, host, type Hit } from '../lib/results';
  import { store } from '../lib/store.svelte';

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
  let kindId = $state<string>(saved.kindId ?? '');
  let key = $state('');
  let query = $state('');
  let busy = $state(false);
  let error = $state('');
  let hits = $state<Hit[]>([]);
  let raw = $state('');
  let showRaw = $state(false);
  let meta = $state<{ status: number; ms: number; via: string } | null>(null);
  let searched = $state(false);
  let input: HTMLInputElement;

  onMount(() => input?.focus());
  $effect(() => { if (!key) key = store.key; });
  $effect(() => {
    try { localStorage.setItem(SAVED, JSON.stringify({ base, method, path, template, kindId })); } catch { /* private mode */ }
  });

  const slug = $derived(base === '/v1/' ? s.default_route : base.replace(/^\/p\/|\/$/g, ''));
  const preset = $derived(s.providers.find((p) => p.slug === slug)?.preset ?? '');
  const kinds = $derived<Kind[]>(KINDS[preset] ?? []);
  const kind = $derived(kinds.find((k) => k.id === kindId) ?? kinds[0]);
  const noProvider = $derived(s.providers.length === 0);
  const noAccount = $derived(!noProvider && s.accounts_total === 0);
  const needsKey = $derived(s.auth_enabled && !key && store.role === 'none');

  async function search(e: SubmitEvent) {
    e.preventDefault();
    const q = query.trim();
    if (!q) return;
    busy = true; error = ''; hits = []; raw = ''; meta = null; searched = true;
    const t0 = performance.now();
    try {
      const how = kind ? { method: kind.method, path: buildPath(kind, q) } : { method, path };
      let url = base + how.path.replace(/^\/+/, '');
      const init: RequestInit = { method: how.method, headers: { ...authHeaders(key || undefined) } };
      if (kind) {
        // fully described by the search type
      } else if (method === 'GET') {
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
        status: res.status, ms: Math.round(performance.now() - t0),
        via: res.headers.get('x-router-account') ?? res.headers.get('x-router-provider') ?? '',
      };
      if (!res.ok) {
        error = res.status === 401 ? 'The router needs a key. Sign in, or paste a client key under Request options.'
          : res.status === 503 ? 'Nothing is set up to answer yet. Add a provider and an account first.'
          : `The search failed (HTTP ${res.status}). The raw response below has the details.`;
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

<PageHead title="Search" lede="Ask through the router and read what comes back. Each search is a real call and uses one credit." />

<div class="stack" style="gap:22px">
  {#if noProvider}
    <div class="note warn"><Icon name="info" /><span>Nothing to search with yet. <a href="#/providers">Add a provider</a>, then an <a href="#/accounts">account</a> with its API key.</span></div>
  {:else if noAccount}
    <div class="note warn"><Icon name="info" /><span>A provider is set up, but it has no API key yet. <a href="#/accounts">Add an account</a>.</span></div>
  {/if}

  {#if kinds.length}
    <div class="seg" role="radiogroup" aria-label="Kind of search" style="justify-self:start;flex-wrap:wrap">
      {#each kinds as k}<button type="button" role="radio" aria-checked={kind?.id === k.id} onclick={() => (kindId = k.id)}>{k.label}</button>{/each}
    </div>
  {/if}

  <form class="ask" onsubmit={search} role="search">
    <Icon name="search" size={20} />
    <input bind:this={input} type="search" bind:value={query} placeholder="What do you want to look up?" aria-label="Search query" disabled={noProvider || noAccount} />
    <button class="btn primary go" disabled={busy || !query.trim() || noProvider || noAccount}>{busy ? 'Searching…' : 'Search'}</button>
  </form>

  <details class="opts">
    <summary>Request options</summary>
    <div class="form">
      <label class="field">Search with<select bind:value={base}>{#each routes as r}<option value={r.value}>{r.label}</option>{/each}</select></label>
      <label class="field">Client key
        <input type="password" class="mono-input" autocomplete="off" bind:value={key} placeholder={s.auth_enabled ? 'client or admin key' : 'not required'} /></label>
      {#if kinds.length}
        <p class="muted wide" style="font-size:13px">Request details are filled in for {preset}. Pick the kind of search above the box.</p>
      {:else}
        <label class="field">Method<select bind:value={method}>{#each ['POST', 'GET'] as m}<option>{m}</option>{/each}</select></label>
        <label class="field">Path<input class="mono-input" bind:value={path} placeholder="search" /></label>
        {#if method === 'POST'}
          <label class="field wide">Request body <span class="hint"><code>{'{query}'}</code> is replaced by your search</span>
            <textarea class="mono-input" rows="2" bind:value={template}></textarea></label>
        {:else}
          <p class="muted wide" style="font-size:13px">Your search is sent as <code>?q=…</code>.</p>
        {/if}
        <p class="faint wide" style="font-size:13px">Providers differ in what they expect. Set this once to match yours; it is remembered in this browser.</p>
      {/if}
    </div>
  </details>

  {#if needsKey}<div class="note warn"><Icon name="alert" /><span>This router needs a key. Sign in from the sidebar, or add a client key under Request options.</span></div>{/if}
  {#if error}<div class="note bad" role="alert"><Icon name="alert" /><span>{error}</span></div>{/if}

  <div aria-live="polite">
    {#if busy}
      <div class="stack" style="gap:26px;margin-top:8px">
        {#each [0, 1, 2] as i}<div class="stack" style="gap:10px"><div class="skel" style="height:11px;width:{120 + i * 30}px"></div><div class="skel" style="height:20px;width:{60 - i * 8}%"></div><div class="skel" style="height:13px;width:{85 - i * 10}%"></div></div>{/each}
      </div>
    {:else}
      {#if meta && !error}
        <p class="faint" style="font-size:13px;margin-bottom:4px">
          {hits.length ? `${hits.length} result${hits.length === 1 ? '' : 's'}` : 'No results to show'}
          · {meta.ms} ms{meta.via ? ` · answered by ${meta.via}` : ''}</p>
      {/if}
      {#each hits as h, i (h.url + i)}
        <article class="hit" style="animation-delay:{i * 30}ms">
          <span class="where">{host(h.url)}</span><br />
          <a class="title" href={h.url} target="_blank" rel="noopener noreferrer">{h.title}</a>
          {#if h.extra}<div class="extra">{h.extra}</div>{/if}
          {#if h.snippet}<p>{h.snippet}</p>{/if}
        </article>
      {/each}
      {#if searched && !error && meta && !hits.length}
        <p class="muted" style="margin-top:12px">The reply did not look like a list of results. Open the raw response to see what came back.</p>
      {/if}
    {/if}
  </div>

  {#if raw}
    <details class="fold" bind:open={showRaw}>
      <summary>Raw response{meta ? ` · HTTP ${meta.status}` : ''}</summary>
      <div class="inner"><pre class="out">{raw}</pre></div>
    </details>
  {/if}
</div>

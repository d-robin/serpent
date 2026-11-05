<script lang="ts">
  import { authHeaders } from '../lib/api';
  import { store } from '../lib/store.svelte';

  const s = $derived(store.status!);
  const routes = $derived([
    { value: '/v1/', label: `/v1/… (default → ${s.default_route})` },
    ...s.providers.map((p) => ({ value: `/p/${p.slug}/`, label: `/p/${p.slug}/…` })),
    ...s.chains.map((c) => ({ value: `/p/${c.slug}/`, label: `/p/${c.slug}/… (chain)` })),
  ]);
  // SerpApi is GET with the query in the URL (read once: these are only starting values).
  const getStyle = store.status?.providers.find((p) => p.slug === store.status?.default_route)?.preset === 'serpapi';  let base = $state('/v1/');
  let method = $state(getStyle ? 'GET' : 'POST');
  let tail = $state(getStyle ? 'search?engine=google&q=coffee+shops+austin' : 'search');
  let key = $state('');
  let body = $state('{"q":"coffee shops austin","num":3}');
  let busy = $state(false);
  let result = $state<{ status: number; ms: number; headers: [string, string][]; text: string } | null>(null);
  let error = $state('');

  $effect(() => { if (!key) key = store.key; });

  const url = $derived(base + tail.replace(/^\/+/, ''));
  const SHOWN = /^(x-router-|x-quota-|x-cache|x-request-id|retry-after|content-type)/i;

  async function send(e: SubmitEvent) {
    e.preventDefault();
    busy = true; error = ''; result = null;
    const t0 = performance.now();
    try {
      const res = await fetch(url, {
        method,
        headers: { ...authHeaders(key || undefined), ...(method !== 'GET' ? { 'Content-Type': 'application/json' } : {}) },
        body: method === 'GET' ? undefined : body,
      });
      const text = await res.text();
      let pretty = text;
      try { pretty = JSON.stringify(JSON.parse(text), null, 2); } catch { /* not JSON */ }
      result = {
        status: res.status, ms: Math.round(performance.now() - t0),
        headers: [...res.headers.entries()].filter(([k]) => SHOWN.test(k)), text: pretty,
      };
      void store.refresh();
    } catch (err) {
      error = err instanceof Error ? err.message : 'request failed';
    } finally { busy = false; }
  }
</script>

<section class="stack">
  <h2>Try it</h2>
  <p class="muted" style="margin:0">Sends a real request through the router. <strong>It spends a credit</strong> on the chosen provider.</p>
  <form class="card form" onsubmit={send}>
    <label class="field">Route<select bind:value={base}>{#each routes as r}<option value={r.value}>{r.label}</option>{/each}</select></label>
    <label class="field">Method<select bind:value={method}>{#each ['POST', 'GET'] as m}<option>{m}</option>{/each}</select></label>
    <label class="field">Path<input bind:value={tail} placeholder="search" /></label>
    <label class="field">Client key<input type="password" autocomplete="off" bind:value={key} placeholder={s.auth_enabled ? 'client or admin key' : 'not required'} /></label>
    {#if method !== 'GET'}<label class="field wide">JSON body<textarea rows="3" bind:value={body} style="font-family:var(--mono)"></textarea></label>{/if}
    <div class="wide actions" style="justify-content:space-between;align-items:center">
      <code>{method} {url}</code><button class="primary" disabled={busy}>{busy ? 'Sending…' : 'Send request'}</button>
    </div>
  </form>

  {#if error}<div class="banner bad" role="alert">{error}</div>{/if}
  {#if result}
    <div class="card stack" aria-live="polite">
      <div style="display:flex;gap:10px;align-items:center"><span class="pill {result.status < 400 ? 'ok' : 'bad'}">{result.status}</span><span class="muted">{result.ms} ms</span></div>
      <dl class="kv">{#each result.headers as [k, v]}<dt>{k}</dt><dd>{v}</dd>{/each}</dl>
      <pre class="out">{result.text || '(empty body)'}</pre>
    </div>
  {/if}
</section>

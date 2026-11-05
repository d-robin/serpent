<script lang="ts">
  import { onMount } from 'svelte';
  import { get, errorMessage, type RequestPage } from '../lib/api';
  import { store } from '../lib/store.svelte';
  import { ago } from '../lib/format';

  const PAGE = 25;
  let outcome = $state('');
  let provider = $state('');
  let text = $state('');
  let offset = $state(0);
  let page = $state<RequestPage | null>(null);
  let error = $state('');
  let loading = $state(false);
  let live = $state(true);

  const providers = $derived(store.status?.providers ?? []);

  async function load() {
    loading = true;
    try {
      const qs = new URLSearchParams({ limit: String(PAGE), offset: String(offset) });
      if (outcome) qs.set('outcome', outcome);
      if (provider) qs.set('provider', provider);
      if (text.trim()) qs.set('q', text.trim());
      page = await get<RequestPage>(`/admin/requests?${qs}`);
      error = '';
    } catch (e) {
      error = e instanceof Error ? e.message : await errorMessage(e as Response);
    } finally { loading = false; }
  }

  function refilter() { offset = 0; void load(); }

  onMount(() => {
    void load();
    // Keep the first page fresh while you are looking at it.
    const t = setInterval(() => { if (live && offset === 0 && !document.hidden) void load(); }, 5000);
    return () => clearInterval(t);
  });

  const from = $derived(page && page.total ? page.offset + 1 : 0);
  const to = $derived(page ? page.offset + page.rows.length : 0);
</script>

<section class="stack">
  <h2>Requests</h2>
  <p class="muted" style="margin:0">
    Every call that went through the router: when, which route, which provider and account answered, the result and how long it took.
    {#if page}The newest {page.kept.toLocaleString('en-US')} are kept; older ones are dropped.{/if}
  </p>

  <div class="card filters">
    <label class="field">Result
      <select bind:value={outcome} onchange={refilter}>
        <option value="">All</option><option value="ok">Succeeded</option><option value="failed">Failed</option>
      </select>
    </label>
    <label class="field">Provider
      <select bind:value={provider} onchange={refilter}>
        <option value="">All</option>{#each providers as p}<option value={p.slug}>{p.name || p.slug}</option>{/each}
      </select>
    </label>
    <label class="field grow">Contains
      <input type="search" bind:value={text} placeholder="path, account or error" oninput={refilter} />
    </label>
    <label class="check"><input type="checkbox" bind:checked={live} /> Live</label>
  </div>

  {#if error}<div class="banner bad" role="alert">{error}</div>{/if}

  <div class="scroll card" style="padding:0">
    <table>
      <thead><tr><th>When</th><th>Method</th><th>Path</th><th class="hide-sm">Provider</th><th>Account</th><th>Result</th><th class="num">ms</th></tr></thead>
      <tbody>
        {#each page?.rows ?? [] as r (r.id)}
          <tr>
            <td class="muted" title={r.ts}>{ago(r.ts)}</td>
            <td class="mono">{r.method}</td>
            <td class="mono">{r.path}{#if r.cached} <span class="pill accent">cache</span>{/if}
              {#if r.error}<div class="muted err">{r.error}</div>{/if}</td>
            <td class="hide-sm mono">{r.provider_slug ?? '—'}</td>
            <td>{r.account ?? '—'}</td>
            <td><span class="pill {r.status < 400 ? 'ok' : 'bad'}">{r.status}</span></td>
            <td class="num">{Math.round(r.latency_ms)}</td>
          </tr>
        {:else}
          <tr><td colspan="7" class="empty">{loading ? 'Loading…' : page && !page.total && (outcome || provider || text) ? 'Nothing matches those filters.' : 'No requests yet. Run a search first.'}</td></tr>
        {/each}
      </tbody>
    </table>
  </div>

  {#if page && page.total}
    <div class="pager">
      <span class="muted">{from}–{to} of {page.total.toLocaleString('en-US')}</span>
      <span class="spacer"></span>
      <button disabled={offset === 0 || loading} onclick={() => { offset = Math.max(0, offset - PAGE); void load(); }}>Newer</button>
      <button disabled={to >= page.total || loading} onclick={() => { offset += PAGE; void load(); }}>Older</button>
    </div>
  {/if}
</section>

<style>
  .filters { display: flex; flex-wrap: wrap; gap: 12px; align-items: end; }
  .filters .grow { flex: 1; min-width: 160px; }
  .check { display: flex; gap: 6px; align-items: center; min-height: 34px; }
  .err { font-size: 12px; }
  .pager { display: flex; gap: 8px; align-items: center; }
  .pager .spacer { flex: 1; }
</style>

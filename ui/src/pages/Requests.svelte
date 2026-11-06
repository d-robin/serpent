<script lang="ts">
  import { onMount } from 'svelte';
  import { get, type RequestPage } from '../lib/api';
  import { ago } from '../lib/format';
  import Icon from '../lib/Icon.svelte';
  import PageHead from '../lib/PageHead.svelte';
  import { store } from '../lib/store.svelte';

  const PAGE = 25;
  let outcome = $state('');
  let provider = $state('');
  let text = $state('');
  let offset = $state(0);
  let page = $state<RequestPage | null>(null);
  let error = $state('');
  let loading = $state(false);
  let live = $state(true);
  let timer: ReturnType<typeof setTimeout> | undefined;

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
      error = e instanceof Error ? e.message : 'could not load the history';
    } finally { loading = false; }
  }
  function refilter() { offset = 0; clearTimeout(timer); timer = setTimeout(() => void load(), 180); }

  onMount(() => {
    void load();
    const t = setInterval(() => { if (live && offset === 0 && !document.hidden) void load(); }, 5000);
    return () => { clearInterval(t); clearTimeout(timer); };
  });

  const from = $derived(page && page.total ? page.offset + 1 : 0);
  const to = $derived(page ? page.offset + page.rows.length : 0);
  const filtered = $derived(!!(outcome || provider || text));
</script>

<PageHead title="Requests" lede="Every call that went through the router: where it went, who answered, how it ended and how long it took." />

<div class="toolbar">
  <div class="search"><Icon name="search" size={15} /><input type="search" bind:value={text} oninput={refilter} placeholder="Filter by path, account or error" aria-label="Filter" /></div>
  <div class="seg" role="radiogroup" aria-label="Result">
    {#each [['', 'All'], ['ok', 'Succeeded'], ['failed', 'Failed']] as [v, l]}
      <button role="radio" aria-checked={outcome === v} onclick={() => { outcome = v; refilter(); }}>{l}</button>
    {/each}
  </div>
  <select bind:value={provider} onchange={refilter} aria-label="Provider">
    <option value="">All providers</option>{#each providers as p}<option value={p.slug}>{p.name || p.slug}</option>{/each}
  </select>
  <label class="toggle"><input type="checkbox" bind:checked={live} /> Live</label>
</div>

{#if error}<div class="note bad" role="alert" style="margin-bottom:16px"><Icon name="alert" /><span>{error}</span></div>{/if}

<div class="scroll-x"><table class="tbl">
  <thead><tr><th>When</th><th>Request</th><th class="hide-sm">Provider</th><th class="hide-sm">Account</th><th>Result</th><th class="r">ms</th></tr></thead>
  <tbody>
    {#each page?.rows ?? [] as r (r.id)}
      <tr>
        <td class="faint" style="white-space:nowrap" title={r.ts}>{ago(r.ts)}</td>
        <td class="m"><span class="faint">{r.method}</span> {r.path}{#if r.cached} <span class="chip">cache</span>{/if}
          {#if r.error}<div class="bad-text" style="font-family:var(--font-sans)">{r.error}</div>{/if}</td>
        <td class="hide-sm m faint">{r.provider_slug ?? '–'}</td>
        <td class="hide-sm">{r.account ?? '–'}</td>
        <td><span class="code {r.status < 400 ? 'ok' : 'bad'}">{r.status}</span></td>
        <td class="r m">{Math.round(r.latency_ms)}</td>
      </tr>
    {/each}
  </tbody>
</table></div>
{#if !page?.rows.length}
  <div class="empty">
    {#if loading && !page}<span class="muted">Loading…</span>
    {:else if filtered}<strong>Nothing matches.</strong>Try a different filter.
    {:else}<strong>No requests yet.</strong>Run a search and it will appear here.
      <div class="row"><a class="btn" href="#/search">Open Search</a></div>{/if}
  </div>
{/if}

{#if page && page.total}
  <div class="pager">
    <span class="tnum">{from}–{to} of {page.total.toLocaleString('en-US')}</span><span class="grow"></span>
    <button class="btn sm" disabled={offset === 0 || loading} onclick={() => { offset = Math.max(0, offset - PAGE); void load(); }}>Newer</button>
    <button class="btn sm" disabled={to >= page.total || loading} onclick={() => { offset += PAGE; void load(); }}>Older</button>
  </div>
  <p class="faint" style="margin-top:10px;font-size:12.5px">The newest {page.kept.toLocaleString('en-US')} calls are kept. Credential-like parameters are never recorded.</p>
{/if}

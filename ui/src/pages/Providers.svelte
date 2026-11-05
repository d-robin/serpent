<script lang="ts">
  import { del, patch, post } from '../lib/api';
  import Copy from '../lib/Copy.svelte';
  import { slugify } from '../lib/format';
  import { store } from '../lib/store.svelte';

  const s = $derived(store.status!);
  const presetKeys = $derived(Object.keys(store.presets));
  let open = $state(false);
  let preset = $state('');
  let f = $state({ slug: '', name: '', base_url: '', auth_style: 'header', auth_header_name: 'X-API-KEY', auth_param_name: 'api_key' });

  function pick(key: string) {
    preset = key;
    const p = store.presets[key];
    if (!p) return;
    f = {
      slug: key, name: p.name, base_url: p.base_url, auth_style: p.auth_style,
      auth_header_name: p.auth_header_name ?? 'X-API-KEY', auth_param_name: p.auth_param_name ?? 'api_key',
    };
  }

  async function add(e: SubmitEvent) {
    e.preventDefault();
    const ok = await store.act(
      () => post('/admin/providers', { ...f, slug: slugify(f.slug), preset: preset || null }),
      `Added provider ${f.slug}`,
    );
    if (ok) { open = false; preset = ''; }
  }

  const accountCount = (id: number) => s.accounts.filter((a) => a.provider_id === id).length;
</script>

<section>
  <header class="section" style="margin-top:0"><h2>Providers</h2><span class="spacer"></span>
    {#if store.isAdmin}<button class="primary" onclick={() => (open = !open)} aria-expanded={open}>{open ? 'Close' : '+ Add provider'}</button>{/if}
  </header>
  <p class="muted">A provider is one upstream SERP API. Accounts belong to a provider; callers reach it at <code>/p/&lt;slug&gt;/…</code>.</p>

  {#if open && store.isAdmin}
    <form class="card form" onsubmit={add} style="margin-bottom:16px">
      <label class="field wide">Start from a preset
        <select value={preset} onchange={(e) => pick(e.currentTarget.value)}>
          <option value="">Custom…</option>
          {#each presetKeys as k}<option value={k}>{store.presets[k].name}</option>{/each}
        </select>
      </label>
      <label class="field">Slug<input bind:value={f.slug} required pattern="[a-z0-9][a-z0-9_-]*" maxlength="32" placeholder="serper" /></label>
      <label class="field">Name<input bind:value={f.name} placeholder="Serper" /></label>
      <label class="field wide">Base URL<input type="url" bind:value={f.base_url} required placeholder="https://api.example.com" /></label>
      <label class="field">Auth style
        <select bind:value={f.auth_style}>
          <option value="header">header</option><option value="query">query parameter</option><option value="bearer">bearer token</option>
        </select></label>
      {#if f.auth_style === 'header'}<label class="field">Header name<input bind:value={f.auth_header_name} /></label>{/if}
      {#if f.auth_style === 'query'}<label class="field">Parameter name<input bind:value={f.auth_param_name} /></label>{/if}
      <div class="wide actions"><button type="button" onclick={() => (open = false)}>Cancel</button><button class="primary">Add provider</button></div>
    </form>
  {/if}

  <div class="scroll"><table>
    <thead><tr><th>Provider</th><th>Upstream</th><th>Auth</th><th>Accounts</th><th>Endpoint</th><th></th></tr></thead>
    <tbody>
      {#each s.providers as p (p.id)}
        <tr>
          <td><strong>{p.name}</strong> <span class="muted mono">{p.slug}</span>
            {#if s.default_route === p.slug}<span class="pill accent">default</span>{/if}
            {#if !p.enabled}<span class="pill disabled">disabled</span>{/if}</td>
          <td class="mono">{p.base_url}</td>
          <td class="mono">{p.auth_style}{p.auth_style === 'header' ? `: ${p.auth_header_name}` : p.auth_style === 'query' ? `: ${p.auth_param_name}` : ''}</td>
          <td class="num">{accountCount(p.id)}</td>
          <td><Copy text="/p/{p.slug}/" /></td>
          <td class="actions">
            {#if store.isAdmin}
              <button class="tiny" onclick={() => store.act(() => patch(`/admin/providers/${p.slug}`, { enabled: !p.enabled }), p.enabled ? 'Disabled' : 'Enabled')}>{p.enabled ? 'Disable' : 'Enable'}</button>
              <button class="tiny danger" onclick={() => confirm(`Delete provider ${p.slug}?`) && store.act(() => del(`/admin/providers/${p.slug}`), 'Deleted')}>Delete</button>
            {/if}
          </td>
        </tr>
      {:else}<tr><td colspan="6" class="empty">No providers yet. Choose “+ Add provider”, then pick a preset or enter your own URL.</td></tr>{/each}
    </tbody>
  </table></div>
  <p class="muted">Presets are starting points — check the provider's docs for current endpoints and auth.</p>
</section>

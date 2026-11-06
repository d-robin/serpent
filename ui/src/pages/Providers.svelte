<script lang="ts">
  import { patch, post, del } from '../lib/api';
  import Copy from '../lib/Copy.svelte';
  import { slugify } from '../lib/format';
  import Icon from '../lib/Icon.svelte';
  import PageHead from '../lib/PageHead.svelte';
  import Sheet from '../lib/Sheet.svelte';
  import { store } from '../lib/store.svelte';

  const s = $derived(store.status!);
  const presetKeys = $derived(Object.keys(store.presets));
  let open = $state(false);
  let preset = $state('');
  let f = $state({ slug: '', name: '', base_url: '', auth_style: 'header', auth_header_name: 'X-API-KEY', auth_param_name: 'api_key' });

  $effect(() => { if (store.intent === 'add-provider') { open = true; store.intent = ''; } });

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
      `Added ${f.name || f.slug}`,
    );
    if (ok) { open = false; preset = ''; }
  }
  async function remove(slug: string) {
    if (await store.ask(`Delete ${slug}?`, 'It must have no accounts and no chain using it.', 'Delete', true))
      void store.act(() => del(`/admin/providers/${slug}`), 'Provider deleted');
  }
  const accountCount = (id: number) => s.accounts.filter((a) => a.provider_id === id).length;
</script>

<PageHead title="Providers" lede="A provider is one search API. Accounts belong to a provider, and callers reach it at /p/slug/.">
  {#snippet tools()}{#if store.isAdmin}<button class="btn primary" onclick={() => (open = true)}><Icon name="plus" size={14} />Add provider</button>{/if}{/snippet}
</PageHead>

{#if s.providers.length}
  <div class="scroll-x"><table class="tbl">
    <thead><tr><th>Provider</th><th class="hide-sm">Upstream</th><th class="hide-sm">Auth</th><th>Accounts</th><th>Address</th><th></th></tr></thead>
    <tbody>
      {#each s.providers as p (p.id)}
        <tr>
          <td>
            <span class="state"><span class="dot {p.enabled ? 'ok' : ''}"></span><strong style="font-weight:600">{p.name}</strong></span>
            <span class="faint m">{p.slug}</span>
            {#if s.default_route === p.slug}<span class="chip signal" style="margin-left:6px">default</span>{/if}
            {#if !p.enabled}<span class="chip" style="margin-left:6px">disabled</span>{/if}
          </td>
          <td class="hide-sm m faint">{p.base_url}</td>
          <td class="hide-sm m faint">{p.auth_style}{p.auth_style === 'header' ? ` · ${p.auth_header_name}` : p.auth_style === 'query' ? ` · ${p.auth_param_name}` : ''}</td>
          <td class="num">{accountCount(p.id)}</td>
          <td><Copy text="/p/{p.slug}/" /></td>
          <td class="act">
            {#if store.isAdmin}
              <button class="btn ghost sm" onclick={() => store.act(() => patch(`/admin/providers/${p.slug}`, { enabled: !p.enabled }), p.enabled ? 'Disabled' : 'Enabled')}>{p.enabled ? 'Disable' : 'Enable'}</button>
              <button class="btn ghost sm danger" onclick={() => remove(p.slug)}>Delete</button>
            {/if}
          </td>
        </tr>
      {/each}
    </tbody>
  </table></div>
  <p class="faint" style="margin-top:18px;font-size:13px">Presets are starting points. Check the provider's own docs for current endpoints and authentication.</p>
{:else}
  <div class="empty">
    <strong>No providers yet.</strong>
    Add the search API you use. Nothing is built in, so you choose.
    {#if store.isAdmin}<div class="row"><button class="btn primary" onclick={() => (open = true)}><Icon name="plus" size={14} />Add provider</button></div>{/if}
  </div>
{/if}

{#if open && store.isAdmin}
  <Sheet title="Add provider" onclose={() => (open = false)}>
    <form id="prov" class="form" onsubmit={add}>
      <label class="field wide">Start from a preset
        <select value={preset} onchange={(e) => pick(e.currentTarget.value)}>
          <option value="">Custom…</option>
          {#each presetKeys as k}<option value={k}>{store.presets[k].name}</option>{/each}
        </select></label>
      <label class="field">Short name<input class="mono-input" bind:value={f.slug} required pattern="[a-z0-9][a-z0-9_-]*" maxlength="32" placeholder="serper" /></label>
      <label class="field">Display name<input bind:value={f.name} placeholder="Serper" /></label>
      <label class="field wide">Base URL<input class="mono-input" type="url" bind:value={f.base_url} required placeholder="https://api.example.com" /></label>
      <label class="field">How the key is sent
        <select bind:value={f.auth_style}><option value="header">Header</option><option value="query">Query parameter</option><option value="bearer">Bearer token</option></select></label>
      {#if f.auth_style === 'header'}<label class="field">Header name<input class="mono-input" bind:value={f.auth_header_name} /></label>{/if}
      {#if f.auth_style === 'query'}<label class="field">Parameter name<input class="mono-input" bind:value={f.auth_param_name} /></label>{/if}
    </form>
    {#snippet footer()}
      <button class="btn ghost" onclick={() => (open = false)}>Cancel</button>
      <button class="btn primary" form="prov">Add provider</button>
    {/snippet}
  </Sheet>
{/if}

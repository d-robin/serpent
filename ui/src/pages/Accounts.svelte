<script lang="ts">
  import { onMount } from 'svelte';
  import { del, get, patch, post, type Account, type ProviderUsage } from '../lib/api';
  import Bar from '../lib/Bar.svelte';
  import { ago, hasUsageLookup } from '../lib/format';
  import Icon from '../lib/Icon.svelte';
  import PageHead from '../lib/PageHead.svelte';
  import Sheet from '../lib/Sheet.svelte';
  import { store } from '../lib/store.svelte';

  const s = $derived(store.status!);
  const groups = $derived(
    s.providers.map((p) => ({ p, rows: s.accounts.filter((a) => a.provider_id === p.id) }))
      .concat([{ p: { id: -1, name: 'Unassigned', slug: '', enabled: true, preset: null, base_url: '' } as never, rows: s.accounts.filter((a) => a.provider_id == null) }])
      .filter((g) => g.rows.length || g.p.id !== -1),
  );
  let open = $state(false);
  let f = $state({ provider_id: 0, label: '', api_key: '', quota_limit: 250, notes: '' });
  let agreed = $state(false);
  const DOCS = 'https://github.com/d-robin/serpent/blob/main/docs/responsible-use.md';
  const existing = $derived(s.accounts.filter((a) => a.provider_id === f.provider_id).length);
  const needsAck = $derived(existing >= 1);
  const pooled = $derived(groups.some((g) => g.rows.length > 1));

  $effect(() => { if (!f.provider_id && s.providers.length) f.provider_id = s.providers[0].id; });
  $effect(() => { if (open) f.quota_limit = s.tunables.default_quota_limit; });
  $effect(() => { if (store.intent === 'add-account' && s.providers.length) { open = true; store.intent = ''; } });

  async function add(e: SubmitEvent) {
    e.preventDefault();
    if (needsAck && !agreed) return;
    const ok = await store.act(() => post('/admin/accounts', { ...f, notes: f.notes || null }), `Added ${f.label || 'account'}`);
    if (ok) { f.label = ''; f.api_key = ''; f.notes = ''; agreed = false; open = false; }
  }

  let usage = $state<Record<number, ProviderUsage | 'loading'>>({});
  const fmt = (n: number | null | undefined) => (n == null ? '?' : n.toLocaleString('en-US'));
  async function check(a: Account) {
    usage[a.id] = 'loading';
    try { usage[a.id] = await get<ProviderUsage>(`/admin/accounts/${a.id}/provider-usage`); }
    catch (e) { usage[a.id] = { supported: true, error: e instanceof Error ? e.message : 'lookup failed' }; }
  }
  const checkAll = () => { for (const g of groups) if (g.p.id !== -1 && hasUsageLookup(g.p)) for (const a of g.rows) void check(a); };
  onMount(() => { if (store.isAdmin) checkAll(); });

  const stateOf = (a: Account) => (a.status === 'active' && a.on_cooldown ? 'cooling down' : a.status);
  const dot = (a: Account) => (a.status === 'invalid' ? 'bad' : a.status === 'disabled' ? '' : a.on_cooldown ? 'warn' : 'ok');

  async function removeAcct(a: Account) {
    if (await store.ask(`Delete ${a.label}?`, 'Its key is removed from the database.', 'Delete', true))
      void store.act(() => del(`/admin/accounts/${a.id}`), 'Account deleted');
  }
  async function resetAll() {
    if (await store.ask('Reset all usage?', 'Sets every account back to 0 used for this period.', 'Reset', true))
      void store.act(() => post('/admin/reset'), 'All usage reset');
  }
</script>

<PageHead title="Accounts" lede="Each API key, what you allow through Serpent, what it has used, and what the provider says is left.">
  {#snippet tools()}
    {#if store.isAdmin}
      <button class="btn ghost" onclick={resetAll}>Reset usage</button>
      <button class="btn" onclick={checkAll}><Icon name="refresh" size={14} />Check allowances</button>
      <button class="btn primary" onclick={() => (open = true)} disabled={!s.providers.length}><Icon name="plus" size={14} />Add account</button>
    {/if}
  {/snippet}
</PageHead>

{#if pooled}
  <div class="note warn" style="margin-bottom:8px"><Icon name="info" />
    <span>Several accounts on one provider: make sure the provider's terms allow it. Pooling accounts to bypass limits can get them suspended. <a href={DOCS} target="_blank" rel="noopener">Responsible use</a></span></div>
{/if}

{#each groups as g (g.p.id)}
  <section class="section" style="margin-top:36px">
    <div class="section-head"><h2>{g.p.name}</h2>{#if g.p.slug}<span class="aside m">{g.p.slug}</span>{/if}
      <span class="grow"></span><span class="aside">{g.rows.length} account{g.rows.length === 1 ? '' : 's'}</span></div>
    <div class="scroll-x"><table class="tbl">
      <thead><tr><th>Account</th><th style="min-width:170px">Your limit</th><th style="min-width:190px">Provider allowance</th><th class="hide-sm">Key</th><th class="hide-sm">Last used</th><th></th></tr></thead>
      <tbody>
        {#each g.rows as a (a.id)}
          <tr>
            <td>
              <span class="state"><span class="dot {dot(a)}"></span><strong style="font-weight:600">{a.label}</strong></span>
              <div class="faint" style="font-size:12px;margin-top:2px;padding-left:15px">{stateOf(a)}{#if a.last_error && a.status !== 'active'} · {a.last_error}{/if}</div>
            </td>
            <td><div class="cell-stack"><Bar used={a.used} limit={a.quota_limit} label="{a.label} usage" />
              <span class="sub">{a.used.toLocaleString('en-US')} of {a.quota_limit.toLocaleString('en-US')} used · {a.available.toLocaleString('en-US')} available</span></div></td>
            <td>
              {#if !hasUsageLookup(g.p)}<span class="faint" title="Serpent can only look this up for providers with a public usage endpoint">Not available</span>
              {:else if !store.isAdmin}<span class="faint">Admin only</span>
              {:else}
                {@const u = usage[a.id]}
                {#if u === 'loading' || u === undefined}<div class="skel" style="height:11px;width:120px"></div>
                {:else if u.error}<span class="bad-text" title={u.error}>{u.error}</span>
                {:else if !u.supported}<span class="faint">{u.note}</span>
                {:else}
                  <div class="cell-stack">
                    <span><strong style="font-weight:600">{fmt(u.remaining)}</strong> <span class="muted">left of {fmt(u.allowance)}</span></span>
                    {#if u.allowance}<Bar used={u.used ?? 0} limit={u.allowance} label="{a.label} provider allowance" />{/if}
                    <span class="sub">{u.plan ?? ''}{u.plan ? ' · ' : ''}{fmt(u.used)} used{u.extra_credits ? ` · +${fmt(u.extra_credits)} extra` : ''}</span>
                    {#if u.remaining != null && a.quota_limit - a.used > u.remaining}
                      <span class="warn-text">Your limit allows {fmt(a.quota_limit - a.used)} more, but the provider has {fmt(u.remaining)} left.</span>
                    {/if}
                  </div>
                {/if}
              {/if}
            </td>
            <td class="hide-sm m faint">{store.hints[a.id] ?? '••••'}</td>
            <td class="hide-sm faint" style="white-space:nowrap">{ago(a.last_used_at)}</td>
            <td class="act">
              {#if store.isAdmin}
                {#if hasUsageLookup(g.p)}<button class="btn ghost icon sm" onclick={() => check(a)} disabled={usage[a.id] === 'loading'} aria-label="Refresh allowance for {a.label}"><Icon name="refresh" size={14} /></button>{/if}
                <button class="btn ghost sm" onclick={() => store.act(() => patch(`/admin/accounts/${a.id}`, { status: a.status === 'active' ? 'disabled' : 'active' }), a.status === 'active' ? 'Disabled' : 'Enabled')}>{a.status === 'active' ? 'Disable' : 'Enable'}</button>
                <button class="btn ghost sm" onclick={() => store.act(() => post(`/admin/accounts/${a.id}/reset`), 'Usage reset')}>Reset</button>
                <button class="btn ghost sm danger" onclick={() => removeAcct(a)}>Delete</button>
              {/if}
            </td>
          </tr>
        {/each}
      </tbody>
    </table></div>
  </section>
{:else}
  <div class="empty">
    <strong>No accounts yet.</strong>
    {s.providers.length ? 'Add the API key you got from your provider.' : 'Add a provider first, then register its keys here.'}
    <div class="row">
      {#if s.providers.length && store.isAdmin}<button class="btn primary" onclick={() => (open = true)}><Icon name="plus" size={14} />Add account</button>
      {:else}<a class="btn primary" href="#/providers">Add a provider</a>{/if}
    </div>
  </div>
{/each}

{#if open && store.isAdmin}
  <Sheet title="Add account" onclose={() => (open = false)}>
    <form id="acct" class="form" onsubmit={add}>
      <label class="field wide">Provider
        <select bind:value={f.provider_id}>{#each s.providers as p}<option value={p.id}>{p.name} ({p.slug})</option>{/each}</select></label>
      <label class="field">Label<input bind:value={f.label} placeholder="main" required /></label>
      <label class="field">Credits per period<input type="number" min="0" bind:value={f.quota_limit} /></label>
      <label class="field wide">API key<input type="password" class="mono-input" autocomplete="off" bind:value={f.api_key} required />
        <span class="hint">Stored on this machine. It is never shown in full again.</span></label>
      <label class="field wide">Notes<input bind:value={f.notes} placeholder="optional" /></label>
      {#if needsAck}
        <div class="note warn wide" role="alert"><Icon name="alert" /><div>
          <strong>Check the provider's terms first.</strong>
          This provider already has {existing} account{existing === 1 ? '' : 's'} here. Many providers forbid using several accounts to get around free-tier limits and may suspend them. Serpent does not check this for you. <a href={DOCS} target="_blank" rel="noopener">Read more</a>
          <label class="toggle" style="margin-top:10px;display:flex;color:var(--text)"><input type="checkbox" bind:checked={agreed} required /> I have read the terms and take responsibility.</label></div></div>
      {/if}
    </form>
    {#snippet footer()}
      <button class="btn ghost" onclick={() => (open = false)}>Cancel</button>
      <button class="btn primary" form="acct">Add account</button>
    {/snippet}
  </Sheet>
{/if}

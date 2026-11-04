<script lang="ts">
  import { del, patch, post, type Account } from '../lib/api';
  import Bar from '../lib/Bar.svelte';
  import { ago } from '../lib/format';
  import { store } from '../lib/store.svelte';

  const s = $derived(store.status!);
  const groups = $derived(
    s.providers.map((p) => ({ p, rows: s.accounts.filter((a) => a.provider_id === p.id) }))
      .concat([{ p: { id: -1, name: 'Unassigned', slug: '', enabled: true } as never, rows: s.accounts.filter((a) => a.provider_id == null) }])
      .filter((g) => g.rows.length || g.p.id !== -1),
  );
  let open = $state(false);
  let f = $state({ provider_id: 0, label: '', api_key: '', quota_limit: 250, notes: '' });
  let agreed = $state(false);
  const DOCS = 'https://github.com/d-robin/serpent/blob/main/docs/responsible-use.md';
  const existing = $derived(s.accounts.filter((a) => a.provider_id === f.provider_id).length);
  const needsAck = $derived(existing >= 1);

  $effect(() => { if (!f.provider_id && s.providers.length) f.provider_id = s.providers[0].id; });
  $effect(() => { if (open) f.quota_limit = s.tunables.default_quota_limit; });

  async function add(e: SubmitEvent) {
    e.preventDefault();
    if (needsAck && !agreed) return;
    const ok = await store.act(
      () => post('/admin/accounts', { ...f, notes: f.notes || null }),
      `Added ${f.label || 'account'}`,
    );
    if (ok) { f.label = ''; f.api_key = ''; f.notes = ''; agreed = false; open = false; }
  }

  const badge = (a: Account) => (a.status === 'active' && a.on_cooldown ? 'cooling' : a.status);
</script>

<section>
  <header class="section" style="margin-top:0"><h2>Accounts</h2><span class="spacer"></span>
    {#if store.isAdmin}
      <button onclick={() => confirm('Zero every account’s usage this period?') && store.act(() => post('/admin/reset'), 'All usage reset')}>Reset all usage</button>
      <button class="primary" onclick={() => (open = !open)} aria-expanded={open} disabled={!s.providers.length}>{open ? 'Close' : '+ Add account'}</button>
    {/if}
  </header>

  {#if open && store.isAdmin}
    <form class="card form" onsubmit={add} style="margin-bottom:16px">
      <label class="field">Provider
        <select bind:value={f.provider_id}>{#each s.providers as p}<option value={p.id}>{p.name} ({p.slug})</option>{/each}</select></label>
      <label class="field">Label<input bind:value={f.label} placeholder="serper-3" required /></label>
      <label class="field">API key<input type="password" autocomplete="off" bind:value={f.api_key} required /></label>
      <label class="field">Credits per period<input type="number" min="0" bind:value={f.quota_limit} /></label>
      <label class="field wide">Notes<input bind:value={f.notes} placeholder="optional" /></label>
      {#if needsAck}
        <div class="wide banner warn" role="alert">
          <strong>Check your provider’s terms first.</strong> This provider already has {existing} account{existing === 1 ? '' : 's'} here.
          Many providers forbid creating or using multiple accounts to get around free-tier limits, and may suspend
          the accounts or ban you. Serpent does not check this for you. <a href={DOCS} target="_blank" rel="noopener">Read more</a>.
          <label class="check"><input type="checkbox" bind:checked={agreed} required /> I have read my provider’s terms and I’m responsible for how I use these accounts.</label>
        </div>
      {/if}
      <div class="wide actions"><button type="button" onclick={() => (open = false)}>Cancel</button><button class="primary">Add account</button></div>
    </form>
  {/if}

  {#each groups as g (g.p.id)}
    <div class="section" style="margin-top:20px">
      <header><h3>{g.p.name}</h3>{#if g.p.slug}<span class="muted mono">{g.p.slug}</span>{/if}</header>
      {#if g.rows.length > 1}
        <p class="banner warn" role="note" style="margin:0 0 10px">
          Several accounts on one provider: make sure {g.p.name}’s terms allow it. Pooling accounts to bypass limits can get them suspended.
          <a href={DOCS} target="_blank" rel="noopener">Responsible use</a>
        </p>
      {/if}
      <div class="scroll"><table>
        <thead><tr><th>#</th><th>Label</th><th>Status</th><th>Key</th><th style="min-width:150px">Quota</th><th>Avail</th><th class="hide-sm">OK/Fail</th><th class="hide-sm">Avg ms</th><th class="hide-sm">Last used</th><th></th></tr></thead>
        <tbody>
          {#each g.rows as a (a.id)}
            <tr>
              <td class="muted">{a.id}</td>
              <td>{a.label}{#if a.last_error && a.status !== 'active'}<div class="muted" style="font-size:12px">{a.last_error}</div>{/if}</td>
              <td><span class="pill {badge(a)}" title={a.on_cooldown ? `cooling until ${a.cooldown_until}` : ''}>{badge(a)}</span></td>
              <td class="mono muted">{store.hints[a.id] ?? '****'}</td>
              <td><Bar used={a.used} limit={a.quota_limit} label="{a.label} quota" /><span class="muted mono" style="font-size:11.5px">{a.used}/{a.quota_limit}</span></td>
              <td class="num">{a.available}</td>
              <td class="hide-sm num">{a.ok}/{a.failed}</td>
              <td class="hide-sm num">{a.avg_latency_ms ?? '—'}</td>
              <td class="hide-sm muted">{ago(a.last_used_at)}</td>
              <td class="actions">
                {#if store.isAdmin}
                  <button class="tiny" onclick={() => store.act(() => patch(`/admin/accounts/${a.id}`, { status: a.status === 'active' ? 'disabled' : 'active' }), a.status === 'active' ? 'Disabled' : 'Enabled')}>{a.status === 'active' ? 'Disable' : 'Enable'}</button>
                  <button class="tiny" onclick={() => store.act(() => post(`/admin/accounts/${a.id}/reset`), 'Usage reset')}>Reset</button>
                  <button class="tiny danger" onclick={() => confirm(`Delete ${a.label}?`) && store.act(() => del(`/admin/accounts/${a.id}`), 'Deleted')}>Delete</button>
                {/if}
              </td>
            </tr>
          {:else}<tr><td colspan="10" class="empty">No accounts for this provider.</td></tr>{/each}
        </tbody>
      </table></div>
    </div>
  {:else}
    <div class="card empty">Add a provider first, then register accounts under it.</div>
  {/each}
</section>

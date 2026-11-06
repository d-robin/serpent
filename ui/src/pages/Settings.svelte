<script lang="ts">
  import { get, patch, type Tunables } from '../lib/api';
  import Icon from '../lib/Icon.svelte';
  import PageHead from '../lib/PageHead.svelte';
  import { store } from '../lib/store.svelte';

  const s = $derived(store.status!);
  const STRATEGY_HELP: Record<string, string> = {
    most_remaining: 'The account with the most headroom first. Burns evenly and keeps small plans in reserve.',
    round_robin: 'Strict rotation. Predictable.',
    least_in_flight: 'Fewest concurrent requests first. Spreads latency under load.',
    least_recently_used: 'Oldest last-used first. Avoids idle accounts.',
    fill_first: 'Lowest account id until it runs dry. Burns trial credits in order.',
    random: 'A uniform random pick.',
  };
  const REFUNDS: [string, string][] = [['connect', 'Connection errors'], ['5xx', 'Server errors'], ['429', 'Rate limited'], ['401', 'Rejected key']];

  let t = $state<Tunables | null>(null);
  let cfg = $state<Record<string, unknown> | null>(null);
  let dirty = $state(false);

  $effect(() => { if (!dirty) t = structuredClone($state.snapshot(s.tunables)); });
  $effect(() => { if (store.isAdmin) get<Record<string, unknown>>('/admin/config').then((c) => (cfg = c), () => {}); });

  function toggleRefund(k: string, on: boolean) {
    if (!t) return;
    t.refund_on = on ? [...new Set([...t.refund_on, k])] : t.refund_on.filter((x) => x !== k);
    dirty = true;
  }
  async function save(e: SubmitEvent) {
    e.preventDefault();
    if (!t) return;
    if (await store.act(() => patch('/admin/tunables', t), 'Settings saved')) dirty = false;
  }
  const strategies = $derived(store.strategies.length ? store.strategies : Object.keys(STRATEGY_HELP));
</script>

<PageHead title="Settings" lede="Tuning that applies immediately and survives restarts. Deployment facts live in the environment, below." />

{#if t}
  <form onsubmit={save} oninput={() => (dirty = true)}>
    <fieldset disabled={!store.isAdmin} style="border:0;padding:0;margin:0;min-width:0">
      <div class="numbered" style="border-top:1px solid var(--line-2)"><div class="n">1</div><div>
        <h2>Rotation</h2><p class="muted" style="margin-bottom:18px">How Serpent chooses which account answers each call.</p>
        <div class="form"><label class="field wide">Strategy
          <select bind:value={t.strategy}>{#each strategies as k}<option value={k}>{k.replaceAll('_', ' ')}</option>{/each}</select>
          <span class="hint">{STRATEGY_HELP[t.strategy] ?? ''}</span></label></div></div></div>

      <div class="numbered"><div class="n">2</div><div>
        <h2>Resilience</h2><p class="muted" style="margin-bottom:18px">What happens when a provider fails.</p>
        <div class="form">
          <label class="field">Retries on other accounts<input type="number" min="0" max="10" bind:value={t.max_retries} /></label>
          <label class="field">Provider timeout (seconds)<input type="number" min="1" max="300" step="1" bind:value={t.upstream_timeout} /></label>
          <label class="field">First cooldown (seconds)<input type="number" min="0" step="1" bind:value={t.cooldown_base_seconds} /></label>
          <label class="field">Longest cooldown (seconds)<input type="number" min="0" step="1" bind:value={t.cooldown_max_seconds} /></label>
          <div class="field wide">Give the credit back when the provider fails with
            <div class="row" style="gap:22px;margin-top:4px;color:var(--text)">
              {#each REFUNDS as [k, l]}<label class="toggle" style="color:var(--text)"><input type="checkbox" checked={t.refund_on.includes(k)} onchange={(e) => toggleRefund(k, e.currentTarget.checked)} /> {l}</label>{/each}
            </div></div></div></div></div>

      <div class="numbered"><div class="n">3</div><div>
        <h2>Limits</h2><p class="muted" style="margin-bottom:18px">Credits per account.</p>
        <div class="form">
          <label class="field">Kept in reserve per account<input type="number" min="0" bind:value={t.quota_reserve} /><span class="hint">Never spent, so you cannot hit zero by accident.</span></label>
          <label class="field">Default limit for new accounts<input type="number" min="0" bind:value={t.default_quota_limit} /></label>
        </div></div></div>
    </fieldset>
    {#if store.isAdmin && dirty}
      <div class="savebar"><span class="muted grow">You have unsaved changes.</span>
        <button type="button" class="btn ghost" onclick={() => (dirty = false)}>Revert</button><button class="btn primary">Save changes</button></div>
    {:else if !store.isAdmin}
      <div class="note" style="margin-top:20px"><Icon name="info" /><span>Read-only. Sign in with an admin key to change settings.</span></div>
    {/if}
  </form>
{/if}

<details class="fold" style="margin-top:36px">
  <summary>Effective configuration <span class="faint" style="font-weight:400">from the environment; change it in <code>.env</code> and restart</span></summary>
  <div class="inner">
    {#if cfg}
      <dl class="kv">{#each Object.entries(cfg) as [k, v]}<dt>{k}</dt><dd>{typeof v === 'object' ? JSON.stringify(v) : String(v)}</dd>{/each}</dl>
    {:else}<p class="muted">{store.isAdmin ? 'Loading…' : 'Visible to admin keys only.'}</p>{/if}
  </div>
</details>

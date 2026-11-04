<script lang="ts">
  import { get, patch, type Tunables } from '../lib/api';
  import { store } from '../lib/store.svelte';

  const s = $derived(store.status!);
  const STRATEGY_HELP: Record<string, string> = {
    most_remaining: 'Account with most headroom first — even burn-down, keeps small plans in reserve.',
    round_robin: 'Strict rotation, predictable.',
    least_in_flight: 'Fewest concurrent requests first — spreads latency under load.',
    least_recently_used: 'Oldest last-used first — avoids idling accounts.',
    fill_first: 'Lowest account id until dry — burns trial credits in order.',
    random: 'Uniform random pick.',
  };
  const REFUNDS = ['connect', '5xx', '429', '401'];

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

<section class="stack">
  <h2>Settings</h2>
  {#if t}
    <form class="card stack" onsubmit={save} oninput={() => (dirty = true)}>
      <h3>Runtime tuning <span class="muted" style="text-transform:none;letter-spacing:0">— applied immediately and persisted</span></h3>
      <fieldset disabled={!store.isAdmin} style="border:0;padding:0;margin:0" class="form">
        <label class="field wide">Rotation strategy
          <select bind:value={t.strategy}>{#each strategies as k}<option value={k}>{k}</option>{/each}</select>
          <span>{STRATEGY_HELP[t.strategy] ?? ''}</span></label>
        <label class="field">Retries on other accounts<input type="number" min="0" max="10" bind:value={t.max_retries} /></label>
        <label class="field">Reserve per account (credits)<input type="number" min="0" bind:value={t.quota_reserve} /></label>
        <label class="field">Default credits for new accounts<input type="number" min="0" bind:value={t.default_quota_limit} /></label>
        <label class="field">Upstream timeout (s)<input type="number" min="1" max="300" step="1" bind:value={t.upstream_timeout} /></label>
        <label class="field">Cooldown base (s)<input type="number" min="0" step="1" bind:value={t.cooldown_base_seconds} /></label>
        <label class="field">Cooldown max (s)<input type="number" min="0" step="1" bind:value={t.cooldown_max_seconds} /></label>
        <div class="field wide"><span>Refund the credit when the upstream fails with…</span>
          <div style="display:flex;gap:16px;flex-wrap:wrap;color:var(--text)">
            {#each REFUNDS as k}<label><input type="checkbox" checked={t.refund_on.includes(k)} onchange={(e) => toggleRefund(k, e.currentTarget.checked)} /> {k}</label>{/each}
          </div></div>
      </fieldset>
      {#if store.isAdmin}<div class="actions"><button type="button" disabled={!dirty} onclick={() => (dirty = false)}>Revert</button><button class="primary" disabled={!dirty}>Save</button></div>
      {:else}<div class="banner">Read-only: sign in with an admin key to change settings.</div>{/if}
    </form>
  {/if}

  <div class="card stack">
    <h3>Effective configuration <span class="muted" style="text-transform:none;letter-spacing:0">— from environment, change in <code>.env</code> and restart</span></h3>
    {#if cfg}
      <dl class="kv">
        {#each Object.entries(cfg) as [k, v]}<dt>{k}</dt><dd>{typeof v === 'object' ? JSON.stringify(v) : String(v)}</dd>{/each}
      </dl>
    {:else}<p class="muted" style="margin:0">{store.isAdmin ? 'Loading…' : 'Visible to admin keys only.'}</p>{/if}
  </div>
</section>

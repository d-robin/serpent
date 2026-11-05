<script lang="ts">
  import Bar from '../lib/Bar.svelte';
  import GettingStarted from '../lib/GettingStarted.svelte';
  import { ago, duration } from '../lib/format';
  import { store } from '../lib/store.svelte';

  const s = $derived(store.status!);
  const byProvider = $derived.by(() => {
    const rows = new Map<number | null, { name: string; limit: number; used: number; usable: number; total: number }>();
    for (const p of s.providers) rows.set(p.id, { name: p.name, limit: 0, used: 0, usable: 0, total: 0 });
    for (const a of s.accounts) {
      const r = rows.get(a.provider_id) ?? { name: 'unassigned', limit: 0, used: 0, usable: 0, total: 0 };
      r.limit += a.quota_limit; r.used += a.used; r.total += 1;
      if (a.status === 'active' && a.available > 0 && !a.on_cooldown) r.usable += 1;
      rows.set(a.provider_id, r);
    }
    return [...rows.values()].filter((r) => r.total > 0);
  });
  const counters = $derived(Object.entries(s.counters).filter(([, v]) => v > 0).sort());
</script>

<h2 class="sr-only">Overview</h2>
{#if store.isAdmin}<GettingStarted />{/if}
<div class="grid">
  <div class="card"><div class="label">Spendable credits</div><div class="value">{s.quota_available_total}</div>
    <div class="foot">of {s.quota_remaining_total} unconsumed</div></div>
  <div class="card"><div class="label">Used this period</div><div class="value">{s.quota_used_total}<span class="muted" style="font-size:15px"> / {s.quota_limit_total}</span></div>
    <Bar used={s.quota_used_total} limit={s.quota_limit_total} label="total quota used" /></div>
  <div class="card"><div class="label">Usable accounts</div><div class="value">{s.accounts_usable}<span class="muted" style="font-size:15px"> / {s.accounts_total}</span></div>
    <div class="foot">{s.accounts_invalid} invalid · {s.accounts_disabled} disabled · {s.accounts_on_cooldown} cooling</div></div>
  <div class="card"><div class="label">Resets in</div><div class="value">{duration(s.resets_in_seconds)}</div>
    <div class="foot">period {s.period}</div></div>
  <div class="card"><div class="label">Requests</div><div class="value">{s.requests_ok}</div>
    <div class="foot">{s.requests_failed} failed · {s.requests_refunded} refunded · {s.in_flight} in flight</div></div>
  <div class="card"><div class="label">Default route</div><div class="value mono" style="font-size:20px">{s.default_route}</div>
    <div class="foot">up {duration(s.uptime_seconds)}</div></div>
</div>

{#if byProvider.length}
  <section class="section">
    <header><h3>By provider</h3></header>
    <div class="grid">
      {#each byProvider as r}
        <div class="card"><strong>{r.name}</strong>
          <div class="foot">{r.usable}/{r.total} usable · {r.used}/{r.limit} used</div>
          <div style="margin-top:8px"><Bar used={r.used} limit={r.limit} label="{r.name} quota used" /></div></div>
      {/each}
    </div>
  </section>
{/if}

{#if counters.length}
  <section class="section">
    <header><h3>Counters</h3></header>
    <div class="card" style="display:flex;flex-wrap:wrap;gap:6px 14px">
      {#each counters as [k, v]}<span class="mono">{k.replace('proxy_', '')}=<strong>{v}</strong></span>{/each}
    </div>
  </section>
{/if}

<section class="section">
  <header><h3>Recent requests</h3><a href="#/requests">See all</a></header>
  <div class="scroll">
    <table>
      <thead><tr><th>When</th><th>Method</th><th>Path</th><th class="hide-sm">Provider</th><th>Account</th><th>Status</th><th>ms</th></tr></thead>
      <tbody>
        {#each s.recent as r (r.id)}
          <tr>
            <td class="muted">{ago(r.ts)}</td><td class="mono">{r.method}</td>
            <td class="mono">{r.path}{#if r.cached} <span class="pill accent">cache</span>{/if}</td>
            <td class="hide-sm mono">{r.provider_slug ?? '—'}</td>
            <td>{r.account ?? '—'}</td>
            <td><span class="pill {r.status < 400 ? 'ok' : 'bad'}" title={r.error ?? ''}>{r.status}</span></td>
            <td class="num">{Math.round(r.latency_ms)}</td>
          </tr>
        {:else}
          <tr><td colspan="7" class="empty">No requests yet.</td></tr>
        {/each}
      </tbody>
    </table>
  </div>
</section>

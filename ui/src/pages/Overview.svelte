<script lang="ts">
  import CountUp from '../lib/CountUp.svelte';
  import { ago, duration } from '../lib/format';
  import GettingStarted from '../lib/GettingStarted.svelte';
  import PageHead from '../lib/PageHead.svelte';
  import Bar from '../lib/Bar.svelte';
  import Copy from '../lib/Copy.svelte';
  import Trace from '../lib/Trace.svelte';
  import { store } from '../lib/store.svelte';

  const s = $derived(store.status!);
  const byProvider = $derived(
    s.providers.map((p) => {
      const rows = s.accounts.filter((a) => a.provider_id === p.id);
      return {
        p, total: rows.length, used: rows.reduce((n, a) => n + a.used, 0), limit: rows.reduce((n, a) => n + a.quota_limit, 0),
        usable: rows.filter((a) => a.status === 'active' && a.available > 0 && !a.on_cooldown).length,
      };
    }),
  );
  const tone = (a: { status: string; used: number; quota_limit: number; on_cooldown: boolean }) =>
    a.status !== 'active' ? 'off' : a.on_cooldown ? 'warn' : a.quota_limit && a.used / a.quota_limit >= 0.9 ? 'bad' : a.quota_limit && a.used / a.quota_limit >= 0.7 ? 'warn' : '';
  const failed = $derived(s.recent.filter((r) => r.status >= 400).length);
</script>

<PageHead title="Overview" lede="Everything routed through Serpent, as it happens." />

{#if store.isAdmin}<GettingStarted />{/if}

{#if s.accounts_total > 0}
  <div class="hero">
    <div>
      <div class="label">Credits you can spend right now</div>
      <div class="hero-num" style="margin-top:14px"><CountUp value={s.quota_available_total} /><small>of {s.quota_limit_total.toLocaleString('en-US')}</small></div>
      <div class="cap" style="margin-top:28px" role="img" aria-label="Usage by account">
        {#each s.accounts as a (a.id)}
          <span class={tone(a)} title="{a.label}: {a.used} of {a.quota_limit} used" style="flex-grow:{Math.max(1, a.quota_limit)}"><i style="width:{a.quota_limit ? Math.min(100, (a.used / a.quota_limit) * 100) : 0}%"></i></span>
        {/each}
      </div>
      <p class="muted" style="margin-top:12px">
        {s.accounts_usable} of {s.accounts_total} account{s.accounts_total === 1 ? '' : 's'} ready
        <span class="faint">· resets in {duration(s.resets_in_seconds)}</span>
        {#if s.accounts_invalid || s.accounts_on_cooldown || s.accounts_disabled}
          <span class="faint">· {[s.accounts_invalid && `${s.accounts_invalid} invalid`, s.accounts_on_cooldown && `${s.accounts_on_cooldown} cooling`, s.accounts_disabled && `${s.accounts_disabled} disabled`].filter(Boolean).join(', ')}</span>
        {/if}
      </p>
    </div>
    <dl class="ledger">
      <div><dt>Served</dt><dd><CountUp value={s.requests_ok} /></dd></div>
      <div><dt>Failed</dt><dd>{s.requests_failed.toLocaleString('en-US')}</dd></div>
      <div><dt>Refunded</dt><dd>{s.requests_refunded.toLocaleString('en-US')}</dd></div>
      <div><dt>In flight</dt><dd>{s.in_flight}</dd></div>
      <div><dt>Default route</dt><dd class="m">{s.default_route || 'none'}</dd></div>
      <div><dt>Uptime</dt><dd>{duration(s.uptime_seconds)}</dd></div>
    </dl>
  </div>
{/if}

<section class="section">
  <div class="section-head"><h2>Activity</h2>
    {#if s.recent.length}<span class="aside">last {Math.min(48, s.recent.length)} calls{failed ? ` · ${failed} failed` : ' · all succeeded'}</span>{/if}</div>
  {#if s.recent.length}<Trace rows={s.recent} />
  {:else}<p class="muted">Nothing yet. Make a request and it will draw here.</p>{/if}
</section>

{#if byProvider.length}
  <section class="section">
    <div class="section-head"><h2>Providers</h2><span class="grow"></span><a class="btn ghost sm" href="#/providers">Manage</a></div>
    <div class="scroll-x"><table class="tbl">
      <thead><tr><th>Provider</th><th>Accounts</th><th style="width:34%">Usage</th><th class="hide-sm">Route</th></tr></thead>
      <tbody>
        {#each byProvider as r (r.p.id)}
          <tr>
            <td><strong style="font-weight:600">{r.p.name}</strong> <span class="faint m">{r.p.slug}</span>
              {#if s.default_route === r.p.slug}<span class="chip signal" style="margin-left:6px">default</span>{/if}</td>
            <td>{r.usable} <span class="faint">of {r.total} ready</span></td>
            <td><div class="cell-stack"><Bar used={r.used} limit={r.limit} label="{r.p.name} usage" /><span class="sub">{r.used.toLocaleString('en-US')} of {r.limit.toLocaleString('en-US')} used</span></div></td>
            <td class="hide-sm"><Copy text="/p/{r.p.slug}/" /></td>
          </tr>
        {/each}
      </tbody>
    </table></div>
  </section>
{/if}

<section class="section">
  <div class="section-head"><h2>Recent requests</h2><span class="grow"></span><a class="btn ghost sm" href="#/requests">View all</a></div>
  {#if s.recent.length}
    <div class="scroll-x"><table class="tbl">
      <thead><tr><th>When</th><th>Request</th><th class="hide-sm">Provider</th><th class="hide-sm">Account</th><th>Result</th><th class="r">ms</th></tr></thead>
      <tbody>
        {#each s.recent.slice(0, 8) as r (r.id)}
          <tr>
            <td class="faint" style="white-space:nowrap">{ago(r.ts)}</td>
            <td class="m"><span class="faint">{r.method}</span> {r.path}{#if r.cached} <span class="chip">cache</span>{/if}</td>
            <td class="hide-sm m faint">{r.provider_slug ?? '–'}</td>
            <td class="hide-sm">{r.account ?? '–'}</td>
            <td><span class="code {r.status < 400 ? 'ok' : 'bad'}" title={r.error ?? ''}>{r.status}</span></td>
            <td class="r m">{Math.round(r.latency_ms)}</td>
          </tr>
        {/each}
      </tbody>
    </table></div>
  {:else}<p class="muted">No requests yet.</p>{/if}
</section>

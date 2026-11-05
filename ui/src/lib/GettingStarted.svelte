<script lang="ts">
  import { store } from './store.svelte';

  const s = $derived(store.status!);
  const hasAccounts = $derived(s.accounts_total > 0);
  const hasTraffic = $derived(s.requests_ok > 0);
  const origin = location.origin;
  const steps = $derived([
    { done: s.providers.length > 0, title: 'Choose a provider', href: '#/providers',
      text: 'None is built in. Pick your search API from the presets (Serper, SerpApi, ScrapingDog, VALUE SERP, Brave) or enter its URL.' },
    { done: hasAccounts, title: 'Add your API keys', href: '#/accounts',
      text: 'Paste one or more provider keys. Serpent shares the credits across them and never shows a key again.' },
    { done: hasTraffic, title: 'Send a test search', href: '#/search',
      text: 'Type a search and watch the quota drop.' },
  ]);
  const allDone = $derived(steps.every((x) => x.done));
</script>

{#if !allDone}
  <section class="card" aria-labelledby="gs-h" style="margin-bottom:16px">
    <h3 id="gs-h" style="margin:0 0 4px">Getting started</h3>
    <p class="muted" style="margin:0 0 12px">Three steps, all in this window.</p>
    <ol class="gs">
      {#each steps as step, i}
        <li class:done={step.done}>
          <span class="n" aria-hidden="true">{step.done ? '✓' : i + 1}</span>
          <div><a href={step.href}><strong>{step.title}</strong></a>{#if step.done}<span class="muted"> · done</span>{/if}
            <div class="muted">{step.text}</div></div>
        </li>
      {/each}
    </ol>
    <p class="muted" style="margin:12px 0 4px">Then point your app at Serpent with your <em>client</em> key (it is in the <code>.env</code> file):</p>
    <pre class="mono snippet">curl -X POST {origin}/v1/search \
  -H "X-Router-Key: $CLIENT_KEY" -H 'Content-Type: application/json' \
  -d '{`{"q":"coffee shops austin"}`}'</pre>
  </section>
{/if}

<style>
  .gs { list-style: none; margin: 0; padding: 0; display: grid; gap: 12px; }
  .gs li { display: flex; gap: 12px; align-items: flex-start; }
  .n { flex: none; width: 26px; height: 26px; border-radius: 50%; display: grid; place-items: center;
       border: 1px solid var(--line); font-size: 13px; color: var(--dim); }
  li.done .n { background: var(--accent); border-color: var(--accent); color: #062c28; font-weight: 700; }
  .snippet { margin: 0; padding: 10px 12px; border: 1px solid var(--line); border-radius: 8px;
             background: var(--panel); overflow-x: auto; font-size: 12.5px; }
</style>

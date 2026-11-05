<script lang="ts">
  import { onMount } from 'svelte';
  import { authHeaders } from '../lib/api';
  import Copy from '../lib/Copy.svelte';
  import { store } from '../lib/store.svelte';

  const origin = location.origin;
  const contractUrl = `${origin}/v1/contract`;
  let text = $state('');
  let error = $state('');
  let loading = $state(true);

  const prompt = $derived(
`Build my app against the Serpent search router described below.

Read the API contract first: ${contractUrl}
(Send the header "X-Router-Key: $ROUTER_KEY"; I will provide the client key as the
environment variable ROUTER_KEY. Never hard-code it and never use a provider's own key.)

Rules:
- Use only the routes and parameters the contract lists.
- Each call costs one credit. On HTTP 429 wait for the Retry-After header; do not loop.
- Responses are the provider's own JSON, unchanged. Do not assume another provider's shape.
- Ask me if something you need is not in the contract.

What I want the app to do: <describe it here>`);

  async function load() {
    loading = true; error = '';
    try {
      const res = await fetch('/v1/contract', { headers: authHeaders() });
      if (!res.ok) throw new Error(res.status === 401 ? 'Sign in first.' : `HTTP ${res.status}`);
      text = await res.text();
    } catch (e) {
      error = e instanceof Error ? e.message : 'could not load the contract';
    } finally { loading = false; }
  }
  onMount(load);

  async function copy(what: string, value: string) {
    try { await navigator.clipboard.writeText(value); store.toast(`${what} copied`); }
    catch { store.toast('Copy failed: select the text manually', true); }
  }
</script>

<section class="stack">
  <h2>Integrate</h2>
  <p class="muted" style="margin:0">
    Building an app on top of this router, or asking an AI to? Give it the contract: a page generated from your
    current setup that lists every route, how to authenticate, what each provider expects and what comes back.
  </p>

  <div class="card stack">
    <h3 style="margin:0">1. The contract address</h3>
    <Copy text={contractUrl} />
    <p class="muted" style="margin:0">Needs a <strong>client key</strong> in the <code>X-Router-Key</code> header (add <code>?format=json</code> for JSON).
      Also at <code>/llms.txt</code> (open, no key) as a pointer for AI tools.</p>
    {#if /^(127\.|localhost|\[::1\])/.test(location.hostname)}
      <div class="banner warn">This address is only reachable from this computer. A cloud AI cannot open it, so use <strong>Copy the contract text</strong> below and paste that instead.</div>
    {/if}
  </div>

  <div class="card stack">
    <h3 style="margin:0">2. Tell your AI</h3>
    <pre class="out">{prompt}</pre>
    <div><button class="primary" onclick={() => copy('Prompt', prompt)}>Copy this prompt</button></div>
    <p class="muted" style="margin:0">It contains no key. Give the client key to your app through its environment, not through the chat.</p>
  </div>

  <div class="card stack">
    <h3 style="margin:0">3. Or paste the contract itself</h3>
    <div><button disabled={!text} onclick={() => copy('Contract', text)}>Copy the contract text</button>
      <button onclick={load} disabled={loading}>Refresh</button></div>
    {#if error}<div class="banner bad" role="alert">{error}</div>{/if}
    {#if text}<details><summary class="muted">Preview</summary><pre class="out" style="max-height:420px">{text}</pre></details>{/if}
  </div>
</section>

<script lang="ts">
  import { onMount } from 'svelte';
  import { authHeaders } from '../lib/api';
  import Copy from '../lib/Copy.svelte';
  import Icon from '../lib/Icon.svelte';
  import PageHead from '../lib/PageHead.svelte';
  import { store } from '../lib/store.svelte';

  const origin = location.origin;
  const contractUrl = `${origin}/v1/contract`;
  let text = $state('');
  let error = $state('');
  let loading = $state(true);
  const local = /^(127\.|localhost|\[::1\])/.test(location.hostname);

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

<PageHead title="Integrate" lede="Building an app on this router, or asking an AI to? Give it the contract: a page generated from your current setup, listing every route, how to sign in, what each provider expects and what comes back." />

<div>
  <section class="numbered"><div class="n">1</div><div class="stack" style="gap:12px">
    <h2>The contract address</h2>
    <Copy text={contractUrl} />
    <p class="muted">Needs a <strong>client key</strong> in the <code>X-Router-Key</code> header. Add <code>?format=json</code> for JSON. <code>/llms.txt</code> is an open pointer for AI tools.</p>
    {#if local}<div class="note warn"><Icon name="info" /><span>This address only works from this computer. A cloud AI cannot open it, so use the contract text in step 3.</span></div>{/if}
  </div></section>

  <section class="numbered"><div class="n">2</div><div class="stack" style="gap:14px">
    <h2>Tell your AI</h2>
    <pre class="out">{prompt}</pre>
    <div><button class="btn primary" onclick={() => copy('Prompt', prompt)}><Icon name="copy" size={14} />Copy this prompt</button></div>
    <p class="muted">It contains no key. Give the client key to your app through its environment, never through the chat.</p>
  </div></section>

  <section class="numbered"><div class="n">3</div><div class="stack" style="gap:14px">
    <h2>Or paste the contract itself</h2>
    <div class="row">
      <button class="btn" disabled={!text} onclick={() => copy('Contract', text)}><Icon name="copy" size={14} />Copy the contract text</button>
      <button class="btn ghost" onclick={load} disabled={loading}><Icon name="refresh" size={14} />Refresh</button>
    </div>
    {#if error}<div class="note bad" role="alert"><Icon name="alert" /><span>{error}</span></div>{/if}
    {#if text}<details class="fold"><summary>Preview</summary><div class="inner"><pre class="out" style="max-height:440px">{text}</pre></div></details>{/if}
  </div></section>
</div>

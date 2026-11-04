<script lang="ts">
  import { del, patch, post, put } from '../lib/api';
  import Copy from '../lib/Copy.svelte';
  import { move, slugify } from '../lib/format';
  import { store } from '../lib/store.svelte';

  const s = $derived(store.status!);
  const routes = $derived([...s.providers.map((p) => p.slug), ...s.chains.map((c) => c.slug)]);

  let editing = $state<string | null>(null); // chain slug, or '+' for new
  let draft = $state({ slug: '', name: '', steps: [] as string[] });
  let addStep = $state('');

  function startNew() { editing = '+'; draft = { slug: '', name: '', steps: [] }; addStep = ''; }
  function startEdit(c: { slug: string; name: string; steps: string[] }) {
    editing = c.slug; draft = { slug: c.slug, name: c.name, steps: [...c.steps] }; addStep = '';
  }
  const available = $derived(s.providers.filter((p) => !draft.steps.includes(p.slug)));

  function push() {
    if (addStep && !draft.steps.includes(addStep)) draft.steps = [...draft.steps, addStep];
    addStep = '';
  }

  async function save(e: SubmitEvent) {
    e.preventDefault();
    const ok = editing === '+'
      ? await store.act(() => post('/admin/chains', { slug: slugify(draft.slug), name: draft.name, steps: draft.steps }), 'Chain created')
      : await store.act(() => patch(`/admin/chains/${editing}`, { name: draft.name, steps: draft.steps }), 'Chain saved');
    if (ok) editing = null;
  }
  const label = (slug: string) => s.providers.find((p) => p.slug === slug)?.name ?? slug;
</script>

<section>
  <header class="section" style="margin-top:0"><h2>Chains &amp; routing</h2><span class="spacer"></span>
    {#if store.isAdmin}<button class="primary" onclick={startNew} disabled={!s.providers.length}>+ New chain</button>{/if}
  </header>
  <p class="muted">A chain tries its providers in order and moves on when one is out of credits or failing. Use it at <code>/p/&lt;chain&gt;/…</code>.</p>

  <div class="card form" style="margin-bottom:16px">
    <label class="field"><span>Default route (what <code>/v1/…</code> uses)</span>
      <select value={s.default_route} disabled={!store.isAdmin}
        onchange={(e) => store.act(() => put('/admin/default-route', { route: e.currentTarget.value }), 'Default route updated')}>
        {#each routes as r}<option value={r}>{r}</option>{/each}
      </select></label>
  </div>

  {#if editing && store.isAdmin}
    <form class="card stack" onsubmit={save} style="margin-bottom:16px">
      <div class="form">
        <label class="field">Slug<input bind:value={draft.slug} disabled={editing !== '+'} required pattern="[a-z0-9][a-z0-9_-]*" maxlength="32" placeholder="web" /></label>
        <label class="field">Name<input bind:value={draft.name} placeholder="Web search" /></label>
      </div>
      <ol class="steps" aria-label="Provider order">
        {#each draft.steps as step, i (step)}
          <li><span class="n">{i + 1}</span><span style="flex:1">{label(step)} <span class="muted mono">{step}</span></span>
            <button type="button" class="tiny" aria-label="Move {step} up" disabled={i === 0} onclick={() => (draft.steps = move(draft.steps, i, -1))}>↑</button>
            <button type="button" class="tiny" aria-label="Move {step} down" disabled={i === draft.steps.length - 1} onclick={() => (draft.steps = move(draft.steps, i, 1))}>↓</button>
            <button type="button" class="tiny danger" aria-label="Remove {step}" onclick={() => (draft.steps = draft.steps.filter((x) => x !== step))}>✕</button>
          </li>
        {:else}<li class="muted">No steps yet — add at least one provider.</li>{/each}
      </ol>
      <div class="actions" style="justify-content:flex-start">
        <select bind:value={addStep} aria-label="Provider to add"><option value="">Add a provider…</option>
          {#each available as p}<option value={p.slug}>{p.name} ({p.slug})</option>{/each}</select>
        <button type="button" onclick={push} disabled={!addStep}>Add step</button>
        <span class="spacer"></span>
        <button type="button" onclick={() => (editing = null)}>Cancel</button>
        <button class="primary" disabled={!draft.steps.length}>Save chain</button>
      </div>
    </form>
  {/if}

  <div class="stack">
    {#each s.chains as c (c.id)}
      <div class="card">
        <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
          <strong>{c.name}</strong><span class="muted mono">{c.slug}</span>
          {#if s.default_route === c.slug}<span class="pill accent">default</span>{/if}
          {#if !c.enabled}<span class="pill disabled">disabled</span>{/if}
          <span class="spacer"></span><Copy text="/p/{c.slug}/" />
          {#if store.isAdmin}
            <button class="tiny" onclick={() => startEdit(c)}>Edit</button>
            <button class="tiny" onclick={() => store.act(() => patch(`/admin/chains/${c.slug}`, { enabled: !c.enabled }), c.enabled ? 'Disabled' : 'Enabled')}>{c.enabled ? 'Disable' : 'Enable'}</button>
            <button class="tiny danger" onclick={() => confirm(`Delete chain ${c.slug}?`) && store.act(() => del(`/admin/chains/${c.slug}`), 'Deleted')}>Delete</button>
          {/if}
        </div>
        <div style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap" class="mono">{#each c.steps as st, i}{#if i}<span class="muted" aria-hidden="true">→</span>{/if}<span>{st}</span>{/each}</div>
      </div>
    {:else}<div class="card empty">No chains yet. Create one to fall back across providers.</div>{/each}
  </div>
</section>

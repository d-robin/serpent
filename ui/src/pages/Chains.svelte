<script lang="ts">
  import { del, patch, post, put } from '../lib/api';
  import Copy from '../lib/Copy.svelte';
  import { move, slugify } from '../lib/format';
  import Icon from '../lib/Icon.svelte';
  import PageHead from '../lib/PageHead.svelte';
  import Sheet from '../lib/Sheet.svelte';
  import { store } from '../lib/store.svelte';

  const s = $derived(store.status!);
  const routes = $derived([...s.providers.map((p) => p.slug), ...s.chains.map((c) => c.slug)]);
  let editing = $state<string | null>(null); // chain slug, or '+' for new
  let draft = $state({ slug: '', name: '', steps: [] as string[] });
  let addStep = $state('');

  $effect(() => { if (store.intent === 'add-chain' && s.providers.length) { startNew(); store.intent = ''; } });

  function startNew() { editing = '+'; draft = { slug: '', name: '', steps: [] }; addStep = ''; }
  function startEdit(c: { slug: string; name: string; steps: string[] }) { editing = c.slug; draft = { slug: c.slug, name: c.name, steps: [...c.steps] }; addStep = ''; }
  const available = $derived(s.providers.filter((p) => !draft.steps.includes(p.slug)));
  const kinds = $derived(new Set(draft.steps.map((x) => s.providers.find((p) => p.slug === x)?.preset ?? x)));

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
  async function remove(slug: string) {
    if (await store.ask(`Delete chain ${slug}?`, '', 'Delete', true)) void store.act(() => del(`/admin/chains/${slug}`), 'Chain deleted');
  }
  const label = (slug: string) => s.providers.find((p) => p.slug === slug)?.name ?? slug;
</script>

<PageHead title="Chains" lede="A chain tries its providers in order and moves on when one is out of credits or failing. Callers use it at /p/chain/.">
  {#snippet tools()}{#if store.isAdmin}<button class="btn primary" onclick={startNew} disabled={!s.providers.length}><Icon name="plus" size={14} />New chain</button>{/if}{/snippet}
</PageHead>

<div class="row" style="padding:0 0 22px;border-bottom:1px solid var(--line);margin-bottom:8px">
  <div style="flex:1;min-width:240px"><strong style="font-weight:600">Default route</strong>
    <div class="muted" style="font-size:13px">What <code>/v1/…</code> uses when a caller does not name a provider.</div></div>
  <select style="width:220px" value={s.default_route} disabled={!store.isAdmin || !routes.length} aria-label="Default route"
    onchange={(e) => store.act(() => put('/admin/default-route', { route: e.currentTarget.value }), 'Default route updated')}>
    {#each routes as r}<option value={r}>{r}</option>{/each}
  </select>
</div>

{#if s.chains.length}
  <div class="scroll-x"><table class="tbl">
    <thead><tr><th>Chain</th><th>Order</th><th>Address</th><th></th></tr></thead>
    <tbody>
      {#each s.chains as c (c.id)}
        <tr>
          <td><span class="state"><span class="dot {c.enabled ? 'ok' : ''}"></span><strong style="font-weight:600">{c.name}</strong></span>
            <span class="faint m">{c.slug}</span>
            {#if s.default_route === c.slug}<span class="chip signal" style="margin-left:6px">default</span>{/if}
            {#if !c.enabled}<span class="chip" style="margin-left:6px">disabled</span>{/if}</td>
          <td><span class="route">{#each c.steps as st, i}{#if i}<Icon name="arrow" size={13} />{/if}<span>{st}</span>{/each}</span></td>
          <td><Copy text="/p/{c.slug}/" /></td>
          <td class="act">
            {#if store.isAdmin}
              <button class="btn ghost sm" onclick={() => startEdit(c)}>Edit</button>
              <button class="btn ghost sm" onclick={() => store.act(() => patch(`/admin/chains/${c.slug}`, { enabled: !c.enabled }), c.enabled ? 'Disabled' : 'Enabled')}>{c.enabled ? 'Disable' : 'Enable'}</button>
              <button class="btn ghost sm danger" onclick={() => remove(c.slug)}>Delete</button>
            {/if}
          </td>
        </tr>
      {/each}
    </tbody>
  </table></div>
{:else}
  <div class="empty"><strong>No chains yet.</strong>Create one to fall back from one provider to another.
    {#if store.isAdmin && s.providers.length}<div class="row"><button class="btn primary" onclick={startNew}><Icon name="plus" size={14} />New chain</button></div>{/if}</div>
{/if}
<div class="note" style="margin-top:28px"><Icon name="info" /><span>A chain sends the <strong>same request</strong> to every step. Serpent does not translate between providers, so use providers that share an API shape.</span></div>

{#if editing && store.isAdmin}
  <Sheet title={editing === '+' ? 'New chain' : `Edit ${draft.slug}`} onclose={() => (editing = null)}>
    <form id="chain" class="stack" onsubmit={save}>
      <div class="form">
        <label class="field">Short name<input class="mono-input" bind:value={draft.slug} disabled={editing !== '+'} required pattern="[a-z0-9][a-z0-9_-]*" maxlength="32" placeholder="web" /></label>
        <label class="field">Display name<input bind:value={draft.name} placeholder="Web search" /></label>
      </div>
      <div class="field">Order <span class="hint">First is tried first.</span></div>
      <ol class="steps-ed" aria-label="Provider order" style="margin-top:-8px">
        {#each draft.steps as step, i (step)}
          <li><span class="n">{i + 1}</span><span style="flex:1">{label(step)} <span class="faint m">{step}</span></span>
            <button type="button" class="btn ghost icon sm" aria-label="Move {step} up" disabled={i === 0} onclick={() => (draft.steps = move(draft.steps, i, -1))}><span style="transform:rotate(-90deg);display:inline-flex"><Icon name="arrow" size={14} /></span></button>
            <button type="button" class="btn ghost icon sm" aria-label="Move {step} down" disabled={i === draft.steps.length - 1} onclick={() => (draft.steps = move(draft.steps, i, 1))}><span style="transform:rotate(90deg);display:inline-flex"><Icon name="arrow" size={14} /></span></button>
            <button type="button" class="btn ghost icon sm danger" aria-label="Remove {step}" onclick={() => (draft.steps = draft.steps.filter((x) => x !== step))}><Icon name="x" size={14} /></button>
          </li>
        {:else}<li class="muted">No steps yet. Add at least one provider.</li>{/each}
      </ol>
      <div class="row">
        <select style="flex:1" bind:value={addStep} aria-label="Provider to add"><option value="">Add a provider…</option>
          {#each available as p}<option value={p.slug}>{p.name} ({p.slug})</option>{/each}</select>
        <button type="button" class="btn" onclick={push} disabled={!addStep}>Add step</button>
      </div>
      {#if kinds.size > 1}<div class="note warn"><Icon name="alert" /><span>These steps are different provider types. The same request goes to each, so a step that does not understand it will fail.</span></div>{/if}
    </form>
    {#snippet footer()}
      <button class="btn ghost" onclick={() => (editing = null)}>Cancel</button>
      <button class="btn primary" form="chain" disabled={!draft.steps.length}>Save chain</button>
    {/snippet}
  </Sheet>
{/if}

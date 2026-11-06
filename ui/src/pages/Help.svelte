<script lang="ts">
  import { onMount } from 'svelte';
  import Icon from '../lib/Icon.svelte';
  import PageHead from '../lib/PageHead.svelte';
  import { store } from '../lib/store.svelte';
  import { DOCS, plain, sections } from '../help/content';
  import Rich from '../help/Rich.svelte';

  const s = $derived(store.status!);
  const ctx = $derived.by(() => {
    const p = s.providers.find((x) => x.slug === s.default_route) ?? s.providers[0];
    return { origin: location.origin, defaultRoute: s.default_route, slug: p?.slug ?? 'provider', preset: p?.preset ?? '', hasProvider: !!p };
  });
  const all = $derived(sections(ctx));
  let q = $state('');
  const shown = $derived(q.trim() ? all.filter((x) => q.toLowerCase().split(/\s+/).filter(Boolean).every((w) => plain(x).includes(w))) : all);
  let active = $state('start');
  let input: HTMLInputElement;

  function jump(id: string) {
    document.getElementById(`help-${id}`)?.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
  }

  onMount(() => {
    // Keep the contents list in step with what is on screen.
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) if (e.isIntersecting) active = e.target.id.replace('help-', '');
    }, { rootMargin: '-15% 0px -70% 0px' });
    const watch = () => document.querySelectorAll('.help-sec').forEach((el) => io.observe(el));
    watch();
    const mo = new MutationObserver(() => { io.disconnect(); watch(); });
    mo.observe(document.querySelector('.help-body')!, { childList: true });
    return () => { io.disconnect(); mo.disconnect(); };
  });
</script>

<PageHead title="Help" lede="How to start it, connect apps and agents, read the logs, fix problems, and move or remove it. The full guides are in the repository docs." />

<div class="help">
  <nav class="help-toc" aria-label="Help contents">
    <div class="search" style="position:relative;margin-bottom:14px">
      <Icon name="search" size={15} />
      <input bind:this={input} type="search" bind:value={q} placeholder="Search help" aria-label="Search help" style="padding-left:34px" />
    </div>
    <ul>
      {#each all as sec}
        <li><button class:on={active === sec.id} class:dim={q.trim() && !shown.includes(sec)} onclick={() => jump(sec.id)}>{sec.title}</button></li>
      {/each}
    </ul>
    <a class="faint docs-link" href={DOCS} target="_blank" rel="noopener noreferrer">All documentation <Icon name="out" size={13} /></a>
  </nav>

  <div class="help-body">
    {#each shown as sec (sec.id)}
      <section class="help-sec" id="help-{sec.id}" aria-labelledby="h-{sec.id}">
        <h2 id="h-{sec.id}">{sec.title}</h2>
        <p class="lede">{sec.lede}</p>
        <Rich blocks={sec.blocks} />
      </section>
    {:else}
      <div class="empty"><strong>Nothing matches “{q}”.</strong>Try a shorter word, or browse the full guides.
        <div class="row"><a class="btn" href={DOCS} target="_blank" rel="noopener noreferrer">Open the documentation</a></div></div>
    {/each}
  </div>
</div>

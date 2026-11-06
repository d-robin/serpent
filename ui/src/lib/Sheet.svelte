<script lang="ts">
  import { onMount, type Snippet } from 'svelte';
  import Icon from './Icon.svelte';
  import { portal } from './portal';
  let { title, onclose, children, footer }: { title: string; onclose: () => void; children: Snippet; footer?: Snippet } = $props();
  let el: HTMLElement;
  onMount(() => {
    const first = el.querySelector<HTMLElement>('input, select, textarea');
    first?.focus();
    const prev = document.activeElement as HTMLElement | null;
    return () => prev?.focus?.();
  });
  function key(e: KeyboardEvent) {
    if (e.key === 'Escape') { e.stopPropagation(); onclose(); }
  }
</script>

<svelte:window onkeydown={key} />
<div class="layer" use:portal>
<div class="scrim" onclick={onclose} role="presentation"></div>
<div class="sheet" bind:this={el} role="dialog" aria-modal="true" aria-label={title}>
  <header><h2>{title}</h2><button class="btn ghost icon" onclick={onclose} aria-label="Close"><Icon name="x" /></button></header>
  <div class="body">{@render children()}</div>
  {#if footer}<footer>{@render footer()}</footer>{/if}
</div>
</div>

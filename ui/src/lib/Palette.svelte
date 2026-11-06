<script lang="ts">
  import { onMount } from 'svelte';
  import Icon from './Icon.svelte';
  import { portal } from './portal';
  import type { PaletteItem as Item } from './palette';
  let { items, onclose }: { items: Item[]; onclose: () => void } = $props();
  let q = $state('');
  let sel = $state(0);
  let input: HTMLInputElement;
  const fuzzy = (needle: string, text: string) => {
    const it = text.toLowerCase()[Symbol.iterator]();
    return [...needle.toLowerCase()].every((c) => { for (const x of it) if (x === c) return true; return false; });
  };
  const shown = $derived(items.filter((i) => !q || fuzzy(q, i.label)));
  const groups = $derived([...new Set(shown.map((i) => i.group))]);
  $effect(() => { void q; sel = 0; });
  onMount(() => input.focus());
  function run(i: Item) { onclose(); i.run(); }
  function key(e: KeyboardEvent) {
    if (e.key === 'Escape') onclose();
    else if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(shown.length - 1, sel + 1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(0, sel - 1); }
    else if (e.key === 'Enter' && shown[sel]) { e.preventDefault(); run(shown[sel]); }
  }
</script>

<div class="layer" use:portal>
<div class="scrim" onclick={onclose} role="presentation"></div>
<div class="pal" role="dialog" aria-modal="true" aria-label="Command palette">
  <input bind:this={input} bind:value={q} onkeydown={key} placeholder="Jump to a page or run an action…" aria-label="Command" autocomplete="off" spellcheck="false" />
  <ul>
    {#each groups as g}
      <li><h5>{g}</h5>
        {#each shown.filter((i) => i.group === g) as i (i.label)}
          <button aria-current={shown[sel] === i ? 'true' : undefined} onmousemove={() => (sel = shown.indexOf(i))} onclick={() => run(i)}>
            <Icon name={i.icon} />{i.label}{#if i.hint}<span class="hint">{i.hint}</span>{/if}
          </button>
        {/each}
      </li>
    {:else}<li><h5>No match</h5></li>{/each}
  </ul>
  <div class="foot"><span><kbd>↑</kbd> <kbd>↓</kbd> move</span><span><kbd>↵</kbd> open</span><span><kbd>esc</kbd> close</span></div>
</div>
</div>

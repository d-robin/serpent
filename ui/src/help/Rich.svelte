<script lang="ts">
  import Icon from '../lib/Icon.svelte';
  import { store } from '../lib/store.svelte';
  import { inline, type Block } from './content';
  let { blocks }: { blocks: Block[] } = $props();

  async function copy(text: string) {
    try { await navigator.clipboard.writeText(text); store.toast('Copied'); }
    catch { store.toast('Copy failed: select the text manually', true); }
  }
</script>

{#each blocks as b}
  {#if b.t === 'p'}<p class="hp">{@html inline(b.text)}</p>
  {:else if b.t === 'h'}<h3 class="hh">{b.text}</h3>
  {:else if b.t === 'ul'}<ul class="hl">{#each b.items as i}<li>{@html inline(i)}</li>{/each}</ul>
  {:else if b.t === 'ol'}<ol class="hl">{#each b.items as i}<li>{@html inline(i)}</li>{/each}</ol>
  {:else if b.t === 'code'}
    <div class="hcode">
      {#if b.label}<div class="hcode-label">{b.label}</div>{/if}
      <pre class="out">{b.text}</pre>
      <button class="btn ghost icon sm hcopy" onclick={() => copy(b.text)} aria-label="Copy this snippet"><Icon name="copy" size={14} /></button>
    </div>
  {:else if b.t === 'table'}
    <div class="scroll-x"><table class="tbl htable">
      <thead><tr>{#each b.head as h}<th>{h}</th>{/each}</tr></thead>
      <tbody>{#each b.rows as r}<tr>{#each r as c, i}<td class:strong={i === 0}>{@html inline(c)}</td>{/each}</tr>{/each}</tbody>
    </table></div>
  {:else if b.t === 'note'}
    <div class="note {b.kind ?? ''}"><Icon name={b.kind === 'warn' ? 'alert' : 'info'} /><span>{@html inline(b.text)}</span></div>
  {/if}
{/each}

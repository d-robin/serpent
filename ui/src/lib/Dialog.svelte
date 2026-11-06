<script lang="ts">
  import { store } from './store.svelte';
  const d = $derived(store.dialog);
  function key(e: KeyboardEvent) { if (e.key === 'Escape') d?.resolve(false); }
  function focus(node: HTMLElement) { node.focus(); }
</script>

<svelte:window onkeydown={key} />
{#if d}
  <div class="scrim" onclick={() => d.resolve(false)} role="presentation"></div>
  <div class="dialog" role="alertdialog" aria-modal="true" aria-labelledby="dlg-t">
    <h2 id="dlg-t">{d.title}</h2>
    {#if d.body}<p class="muted">{d.body}</p>{/if}
    <div class="row" style="justify-content:flex-end;margin-top:22px">
      <button class="btn ghost" onclick={() => d.resolve(false)}>Cancel</button>
      <button use:focus class="btn {d.danger ? 'danger' : 'primary'}" onclick={() => d.resolve(true)}>{d.label}</button>
    </div>
  </div>
{/if}

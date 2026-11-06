<script lang="ts">
  import Icon from './Icon.svelte';
  import { store } from './store.svelte';
  let { text, label = '' }: { text: string; label?: string } = $props();
  let done = $state(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      done = true;
      setTimeout(() => (done = false), 1400);
    } catch {
      store.toast('Copy failed: select the text manually', true);
    }
  }
</script>

<span class="endpoint"><code>{label || text}</code>
  <button class="btn ghost icon sm" onclick={copy} aria-label="Copy {text}"><Icon name={done ? 'check' : 'copy'} size={14} /></button></span>

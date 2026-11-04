<script lang="ts">
  import { store } from './store.svelte';
  let { text }: { text: string } = $props();
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      store.toast('Copied');
    } catch {
      store.toast('Copy failed — select the text manually', true);
    }
  }
</script>

<span class="endpoint"><code>{text}</code>
  <button class="tiny" onclick={copy} aria-label="Copy {text}">Copy</button></span>

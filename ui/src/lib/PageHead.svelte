<script lang="ts">
  import type { Snippet } from 'svelte';
  let { title, lede = '', tools }: { title: string; lede?: string; tools?: Snippet } = $props();
</script>

<header class="page-head">
  <div class="titles"><h1>{title}</h1>{#if lede}<p>{lede}</p>{/if}</div>
  {#if tools}<div class="tools">{@render tools()}</div>{/if}
</header>

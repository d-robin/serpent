<script lang="ts">
  import type { RequestRow } from './api';
  // The last calls as a strip: height is how long each took, colour is how it ended.
  let { rows }: { rows: RequestRow[] } = $props();
  const items = $derived([...rows].reverse().slice(-48));
  const max = $derived(Math.max(2, ...items.map((r) => r.latency_ms)));
  // Log scale: one slow call should not flatten every other bar. Failures stay visible.
  const h = (r: RequestRow) => Math.max(r.status < 400 ? 14 : 30, (Math.log1p(r.latency_ms) / Math.log1p(max)) * 100);
</script>

<div class="trace" role="img" aria-label="Latency and outcome of the last {items.length} requests">
  {#each items as r, i (r.id)}
    <i class={r.status < 400 ? 'ok' : 'bad'} style="height:{h(r)}%;animation-delay:{i * 8}ms"
       title="{r.method} {r.path} · {r.status} · {Math.round(r.latency_ms)} ms"></i>
  {/each}
</div>

<script lang="ts">
  import { untrack } from 'svelte';
  let { value, format = (n: number) => n.toLocaleString('en-US') }: { value: number; format?: (n: number) => string } = $props();
  let shown = $state(0);
  let first = true;
  $effect(() => {
    const to = value;
    const from = untrack(() => shown);
    if (first || matchMedia('(prefers-reduced-motion: reduce)').matches) {
      first = false;
      if (matchMedia('(prefers-reduced-motion: reduce)').matches) { shown = to; return; }
    }
    const t0 = performance.now();
    let raf = requestAnimationFrame(function step(t) {
      const k = Math.min(1, (t - t0) / 800);
      shown = from + (to - from) * (1 - Math.pow(1 - k, 4));
      if (k < 1) raf = requestAnimationFrame(step);
    });
    return () => cancelAnimationFrame(raf);
  });
</script>

{format(Math.round(shown))}

<script lang="ts">
  import { barClass, pct } from './format';
  let { used, limit, label = 'quota used' }: { used: number; limit: number; label?: string } = $props();
  const p = $derived(pct(used, limit));
</script>

<div class="gauge {barClass(p)}" role="progressbar" aria-label={label} aria-valuemin="0" aria-valuemax={limit} aria-valuenow={used}>
  <i style="width:{p}%"></i>
</div>

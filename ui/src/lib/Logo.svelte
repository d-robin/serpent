<script lang="ts">
  // The mark: one line that is both a snake and a signal; the head is the live dot.
  let { size = 28 }: { size?: number } = $props();
</script>

<svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden="true">
  <path d="M23 9.6C23 5.4 9 5.4 9 11.5c0 5.4 14 3.4 14 9.1 0 6-14 6-14 2" stroke="currentColor" stroke-width="3" stroke-linecap="round"/>
  <circle cx="23" cy="9.6" r="3.4" fill="var(--signal)"/>
</svg>

<script lang="ts">
  import Icon from './Icon.svelte';
  import { store } from './store.svelte';

  const s = $derived(store.status!);
  const steps = $derived([
    { done: s.providers.length > 0, title: 'Choose a provider', href: '#/providers',
      text: 'None is built in. Pick your search API from a preset, or enter its address.' },
    { done: s.accounts_total > 0, title: 'Add an API key', href: '#/accounts',
      text: 'Paste one or more provider keys. Serpent shares the credits and never shows a key again.' },
    { done: s.requests_ok > 0, title: 'Send a first search', href: '#/search',
      text: 'Type a query and watch the credits move.' },
  ]);
  const left = $derived(steps.filter((x) => !x.done).length);
</script>

{#if left}
  <section class="checklist" aria-label="Setup">
    {#each steps as step}
      <a href={step.href} class:done={step.done}>
        <span class="tick">{#if step.done}<Icon name="check" size={12} />{/if}</span>
        <span><strong>{step.title}</strong><div class="sub">{step.text}</div></span>
        <Icon name="arrow" />
      </a>
    {/each}
    <p class="faint" style="margin:14px 0 0;font-size:13px">Need a hand? <a href="#/help">Open Help</a> for the quick start, connecting apps and troubleshooting.</p>
  </section>
{/if}

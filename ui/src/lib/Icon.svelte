<script lang="ts">
  // 16px line icons, drawn for this interface (1.5 stroke, round joins). Decorative: labels live in text.
  const P: Record<string, string> = {
    overview: '<path d="M1.75 8.5h2.6l1.65-4.6 3 8.2 1.7-3.6h3.55"/>',
    search: '<circle cx="7" cy="7" r="4.4"/><path d="m10.4 10.4 3.35 3.35"/>',
    requests: '<path d="M2.5 4h11M2.5 8h11M2.5 12h6.5"/>',
    providers: '<rect x="2" y="2.75" width="12" height="4.25" rx="1.5"/><rect x="2" y="9" width="12" height="4.25" rx="1.5"/><path d="M4.75 4.9h.01M4.75 11.1h.01"/>',
    accounts: '<circle cx="5.6" cy="10.4" r="2.6"/><path d="m7.5 8.5 5.6-5.6M10.8 5.2l1.7 1.7"/>',
    chains: '<circle cx="3.5" cy="4" r="1.5"/><circle cx="12.5" cy="12" r="1.5"/><path d="M5 4h2.6A2.4 2.4 0 0 1 10 6.4v3.2a2.4 2.4 0 0 0 2.4 2.4"/>',
    settings: '<path d="M2.5 5h5.2M11.6 5h1.9M2.5 11h1.9M8.3 11h5.2"/><circle cx="9.6" cy="5" r="1.6"/><circle cx="6.4" cy="11" r="1.6"/>',
    integrate: '<path d="m5.8 4.2-3.3 3.8 3.3 3.8M10.2 4.2l3.3 3.8-3.3 3.8"/>',
    raw: '<path d="M2.5 4.5 6 8l-3.5 3.5M7.5 12h6"/>',
    plus: '<path d="M8 3v10M3 8h10"/>',
    x: '<path d="m4 4 8 8M12 4l-8 8"/>',
    check: '<path d="m3 8.6 3.4 3.4L13 4.6"/>',
    copy: '<rect x="5.25" y="5.25" width="8" height="8" rx="1.75"/><path d="M3.25 10.5V4.75a1.5 1.5 0 0 1 1.5-1.5h5.75"/>',
    arrow: '<path d="M3 8h10M9 4l4 4-4 4"/>',
    out: '<path d="M5.5 10.5 10.5 5.5M6 5.5h4.5V10"/>',
    sun: '<circle cx="8" cy="8" r="2.6"/><path d="M8 1.9v1.3M8 12.8v1.3M1.9 8h1.3M12.8 8h1.3M3.7 3.7l.9.9M11.4 11.4l.9.9M12.3 3.7l-.9.9M4.6 11.4l-.9.9"/>',
    moon: '<path d="M13.2 9.6A5.6 5.6 0 0 1 6.4 2.8a5.6 5.6 0 1 0 6.8 6.8Z"/>',
    menu: '<path d="M2.5 5h11M2.5 8h11M2.5 11h11"/>',
    refresh: '<path d="M13.2 8a5.2 5.2 0 1 1-1.7-3.85M13.2 2.8v3h-3"/>',
    trash: '<path d="M3 4.5h10M6.3 4.5V3h3.4v1.5M4.4 4.5l.55 8.25h6.1l.55-8.25"/>',
    exit: '<path d="M6.2 3H4.2A1.2 1.2 0 0 0 3 4.2v7.6A1.2 1.2 0 0 0 4.2 13h2M10.2 5.4 12.8 8l-2.6 2.6M12.8 8H6.6"/>',
    info: '<circle cx="8" cy="8" r="5.8"/><path d="M8 7.2v3.6M8 5.2v.01"/>',
    alert: '<path d="M8 2.6 14.1 13H1.9L8 2.6ZM8 6.6v3M8 11.3v.01"/>',
    key: '<circle cx="5.6" cy="10.4" r="2.6"/><path d="m7.5 8.5 5.6-5.6"/>',
    help: '<circle cx="8" cy="8" r="5.8"/><path d="M6.3 6.3a1.8 1.8 0 1 1 2.6 1.6c-.6.4-.9.8-.9 1.4M8 11.5v.01"/>',
    dots: '<path d="M3.5 8h.01M8 8h.01M12.5 8h.01"/>',
  };
  let { name, size = 16 }: { name: string; size?: number } = $props();
</script>

<svg class="ico" width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor"
     stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
  {@html P[name] ?? ''}
</svg>

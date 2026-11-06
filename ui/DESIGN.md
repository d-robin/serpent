# Snake Charmer design brief

The standing rule: this interface must look **designed**, not generated. Read this before
changing any UI. (A common failure is swapping one default look for another; decisions below
are deliberate, so keep to them or change them on purpose.)

## Idea

An instrument panel for a router. Calm, precise, typographic. Numbers are the heroes; chrome
stays out of the way. One accent, used as a *signal* (healthy flow, focus, the primary action),
never as decoration.

## What we avoid (the "AI tells")

Purple/indigo or teal-to-blue gradients, gradient text or gauges, everything inside a card,
cards inside cards, oversized radii, a coloured stripe on one edge of banners and toasts, tinted
pill badges for every status, emoji as icons, a centred hero with three equal feature cards,
default fonts (Inter, Geist, system-ui), uppercase letter-spaced labels everywhere, invented
placeholder numbers, and the "cream paper + terracotta" escape route.

## System

- **Type:** Instrument Serif for page titles and hero numerals (the one expressive voice),
  Instrument Sans for UI, IBM Plex Mono for data, keys and paths. All bundled (OFL), no CDN.
  Tabular numerals wherever numbers align.
- **Colour:** neutral graphite (dark) and chalk (light) with a tiny cool bias; one accent,
  signal lime (`--signal`); amber and coral only for warnings and failures. In light mode the
  primary button is ink, not the accent. Both themes are first-class. **Light is the default** and the system setting is deliberately ignored; dark applies only when someone chooses it (remembered in the browser).
- **Surfaces:** hairlines over boxes. Tables sit directly on the page. Cards are for forms and
  popovers only. Radii: 6 (controls), 10 (surfaces), 16 (sheets). Shadows only on things that
  float (palette, sheet, toast).
- **Layout:** fixed sidebar, a serif page title with one line of description, content on a
  12-column grid with generous whitespace. Mobile: top bar and a slide-over menu.
- **Motion:** 120 ms for feedback, 200 ms for movement, one easing curve. Numbers count up,
  gauges fill, pages fade in 6 px. Everything respects `prefers-reduced-motion`.
- **Detail:** visible focus rings, keyboard everywhere (`Ctrl/Cmd K` palette, `g` then a letter
  to jump), real empty, loading and error states, no data invented for display.

## Checklist before shipping a UI change

Dark and light, 1440 / 1024 / 390 wide, keyboard only, reduced motion, long strings, empty and
error states, and "would this pass for a product from a good studio?"

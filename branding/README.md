# Branding

Logos for **Serpent** (the gateway) and **Snake Charmer** (its control UI).
Regenerate everything with `./_export.sh` (needs Python 3 and Inkscape;
shapes live in `_build.py`).

## The marks

| Mark | Idea |
| --- | --- |
| **Serpent** `serpent-logo*.svg` | A coiled snake that rises as a tree (the *Ent*). The trunk is the one router key; the branches fan out to provider accounts. |
| **Snake Charmer** `snake-charmer-logo*.svg` | A basket and a flute with a snake rising as a signal curve — the thing you use to charm the Serpent. |

The name is styled **SerpEnt** (SERP + Ent) in headings and the wordmark, `serpent`
in the CLI/repo, and **Snake Charmer** in prose.

## Files

| Suffix | Use |
| --- | --- |
| `*.svg` (no suffix) | Adaptive: light colours by default, switches to the bright palette under `prefers-color-scheme: dark` (works in `<img>` and browsers). |
| `*-dark.svg` | Fixed bright palette, for dark backgrounds. |
| `*-light.svg` | Fixed darker palette, for light backgrounds. |
| `*-favicon.svg` | Mark on a rounded dark tile; use as `<link rel="icon">`. |
| `social-card.svg`, `banner.svg` | 1280x640 repository social preview; README banner. |
| `png/` | Exports: favicons (32/180/512), logos (512), wordmarks (1520), social card, banner. |

README snippet with automatic light/dark switching:

```html
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="branding/serpent-wordmark-dark.svg">
  <img alt="SerpEnt" src="branding/serpent-wordmark-light.svg" width="360">
</picture>
```

## Palette

| Role | Dark bg | Light bg |
| --- | --- | --- |
| Teal (accent, "Ent") | `#4fd1c5` | `#17a094` |
| Periwinkle (accent 2) | `#7c9cff` | `#4a63e0` |
| Leaf green | `#8bd96b` | `#3f9b3a` |
| Text | `#e6edf3` | `#0b0f14` |
| Background / ink | `#0b0f14` | `#ffffff` |

Teal and periwinkle match the dashboard theme. Body gradient runs periwinkle → teal, bottom to top.

## Rules

- Keep clear space of at least the snake's head width around a mark.
- Do not recolour, rotate, stretch or add effects. Use the `-light`/`-dark` file that fits the background.
- Minimum size: 16 px for favicons (the tile versions), 48 px for the mark.
- Wordmark text is outlined (no font needed). The typeface used is Avenir Next Bold.
- Fine to reuse for projects that attribute Serpent as required by the Apache-2.0 `NOTICE`; do not use the marks to imply endorsement of a fork.

#!/usr/bin/env python3
"""Generates every logo SVG in this folder from the shapes below.

    python3 branding/_build.py      # writes *.svg (text is still live)
    branding/_export.sh             # outlines text, exports PNGs (needs Inkscape)
"""
from pathlib import Path

OUT = Path(__file__).parent

# name -> (a=teal, b=periwinkle, c=leaf green, ink=eyes/detail, bg)
DARK = dict(a="#4fd1c5", b="#7c9cff", c="#8bd96b", ink="#0b0f14", text="#e6edf3", dim="#8b9cad")
LIGHT = dict(a="#17a094", b="#4a63e0", c="#3f9b3a", ink="#ffffff", text="#0b0f14", dim="#52606d")


def style(p, adaptive=False):
    def rules(q):
        return (f".sa{{stroke:{q['a']}}}.sb{{stroke:{q['b']}}}.sc{{stroke:{q['c']}}}"
                f".fa{{fill:{q['a']}}}.fb{{fill:{q['b']}}}.fc{{fill:{q['c']}}}"
                f".s1{{stop-color:{q['a']}}}.s2{{stop-color:{q['b']}}}"
                f".ink{{fill:{q['ink']}}}.tx{{fill:{q['text']}}}.dim{{fill:{q['dim']}}}")
    css = rules(p)
    if adaptive:
        css += "@media (prefers-color-scheme:dark){" + rules(DARK) + "}"
    return f"<style>{css}</style>"


# ---- marks (256 x 256 box) -------------------------------------------------
SERPENT = """
<defs><linearGradient id="g" x1="0" y1="1" x2="0" y2="0">
<stop offset="0" class="s2"/><stop offset="1" class="s1"/></linearGradient>
<path id="leaf" d="M0 0 C13 -9 14 -32 0 -46 C-14 -32 -13 -9 0 0Z"/></defs>
<g fill="none" stroke-linecap="round" stroke-linejoin="round">
  <!-- trunk: a coil that rises, bending like a growing tree -->
  <path d="M46 238 C46 254 210 254 210 238 C210 222 66 224 66 208 C66 190 128 198 128 166 C128 140 104 134 106 110 C108 94 124 90 128 72"
        stroke="url(#g)" stroke-width="18"/>
  <!-- branches: one key fans out to many accounts -->
  <path d="M106 114 C92 104 72 98 64 70" class="sa" stroke-width="10"/>
  <path d="M126 150 C152 138 176 126 188 94" class="sb" stroke-width="10"/>
  <path d="M130 184 C154 178 178 176 200 154" class="sc" stroke-width="10"/>
</g>
<use href="#leaf" transform="translate(64 70) rotate(-18)" class="fa"/>
<use href="#leaf" transform="translate(188 94) rotate(22)" class="fb"/>
<use href="#leaf" transform="translate(200 154) rotate(52)" class="fc"/>
<!-- head, in profile, facing up-right -->
<g transform="translate(130 50) rotate(14)">
  <path d="M-4 -34 C14 -34 22 -14 18 6 C15 22 6 36 -4 36 C-14 36 -23 22 -24 6 C-25 -14 -16 -34 -4 -34Z" fill="url(#g)"/>
  <circle cx="7" cy="-8" r="5.2" class="ink"/>
  <path d="M-4 -34 L-4 -44 M-4 -44 L-11 -52 M-4 -44 L3 -52" class="sa" stroke-width="4.5"
        stroke-linecap="round" fill="none"/>
</g>
"""

CHARMER = """
<defs><linearGradient id="g" x1="0" y1="1" x2="0" y2="0">
<stop offset="0" class="s2"/><stop offset="1" class="s1"/></linearGradient></defs>
<g fill="none" stroke-linecap="round" stroke-linejoin="round">
  <!-- signal-snake: a wave whose amplitude is the remaining quota -->
  <path d="M128 176 C178 158 78 132 128 110 C174 90 86 70 124 48" stroke="url(#g)" stroke-width="17"/>
  <!-- the tune -->
  <path d="M172 44 C183 54 183 70 172 80" class="sa" stroke-width="7" opacity=".9"/>
  <path d="M190 32 C208 48 208 76 190 92" class="sa" stroke-width="7" opacity=".55"/>
</g>
<!-- head -->
<path d="M124 20 C141 20 148 37 144 50 C141 59 133 64 124 64 C115 64 107 59 104 50 C100 37 107 20 124 20Z"
      fill="url(#g)"/>
<circle cx="115" cy="39" r="4" class="ink"/><circle cx="133" cy="39" r="4" class="ink"/>
<!-- basket: mouth, body, weave -->
<path d="M60 172 H196 L182 236 C180 246 173 252 163 252 H93 C83 252 76 246 74 236Z" class="fb"/>
<g fill="none" stroke="#0b0f14" stroke-width="5" opacity=".36" stroke-linecap="round">
  <path d="M66 198 H190 M71 224 H185 M100 180 L92 248 M128 182 V252 M156 180 L164 248"/>
</g>
<ellipse cx="128" cy="172" rx="68" ry="12" class="fa"/>
<ellipse cx="128" cy="173" rx="52" ry="7" fill="#0b0f14" opacity=".55"/>
<!-- flute, lying across the front -->
<g transform="rotate(-38 40 226)">
  <rect x="16" y="215" width="134" height="22" rx="11" class="fc"/>
  <rect x="134" y="212" width="22" height="28" rx="6" class="fc"/>
  <g fill="#0b0f14" opacity=".55"><circle cx="68" cy="226" r="4.6"/><circle cx="86" cy="226" r="4.6"/>
  <circle cx="104" cy="226" r="4.6"/><circle cx="122" cy="226" r="4.6"/></g>
</g>
"""


def svg(body, w, h, p, adaptive=False, bg=None):
    r = f'<rect width="{w}" height="{h}" fill="{bg}"/>' if bg else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">'
            f"{style(p, adaptive)}{r}{body}</svg>\n")


def mark_group(body, x, y, s):
    return f'<g transform="translate({x} {y}) scale({s})">{body}</g>'


# gradient ids must be unique per document; every file holds one mark pair at most
def wordmark(mark, name, accent, p, adaptive=False, w=760, h=260):
    w = 1060 if 'Snake' in name else w
    s = 0.9
    body = mark_group(mark, 10, 12, s)
    ty = 160
    text = (f'<text x="262" y="{ty}" font-family="Avenir Next, Futura, Helvetica Neue, Arial, sans-serif" '
            f'font-size="104" font-weight="700" letter-spacing="-2"><tspan class="tx">{name}</tspan>'
            f'<tspan class="{accent}">{{ENT}}</tspan></text>')
    return svg(body + text, w, h, p, adaptive)


def write(name, content):
    (OUT / name).write_text(content)


def variants(base, builder):
    write(f"{base}.svg", builder(LIGHT, True))
    write(f"{base}-dark.svg", builder(DARK, False))
    write(f"{base}-light.svg", builder(LIGHT, False))


# marks
variants("serpent-logo", lambda p, a: svg(SERPENT, 256, 256, p, a))
variants("snake-charmer-logo", lambda p, a: svg(CHARMER, 256, 256, p, a))

# wordmarks ("Ent" in the accent colour)
def wm(mark, first, rest, cls):
    def b(p, a):
        s = wordmark(mark, first, cls, p, a)
        return s.replace("{ENT}", rest)
    return b

variants("serpent-wordmark", wm(SERPENT, "Serp", "Ent", "fa"))
variants("snake-charmer-wordmark", wm(CHARMER, "Snake&#160;", "Charmer", "fa"))

# favicons: mark on a rounded dark tile (readable in any browser chrome)
for nm, m in (("serpent", SERPENT), ("snake-charmer", CHARMER)):
    body = '<rect width="256" height="256" rx="56" class="tilebg" fill="#0b0f14"/>' + mark_group(m, 28, 28, 0.78)
    write(f"{nm}-favicon.svg", svg(body, 256, 256, DARK))

# social card + banner (dark art, both products)
def card(w, h, big):
    ms = 1.0 if big else 0.8
    body = f'<rect width="{w}" height="{h}" fill="#0b0f14"/>'
    body += f'<circle cx="{w*0.2:.0f}" cy="{h*0.2:.0f}" r="{h*0.55:.0f}" fill="#4fd1c5" opacity=".05"/>'
    body += f'<circle cx="{w*0.95:.0f}" cy="{h*1.0:.0f}" r="{h*0.6:.0f}" fill="#7c9cff" opacity=".07"/>'
    cy = (h - 256 * ms * 1.0) / 2
    body += mark_group(SERPENT, 70 if big else 40, cy, ms)
    tx = (70 if big else 40) + 256 * ms + (50 if big else 34)
    f = "Avenir Next, Futura, Helvetica Neue, Arial, sans-serif"
    fs, fs2 = (112, 34) if big else (72, 22)
    ty = h / 2 - (0 if big else 22)
    body += (f'<text x="{tx:.0f}" y="{ty:.0f}" font-family="{f}" font-size="{fs}" font-weight="700" '
             f'letter-spacing="-2"><tspan fill="#e6edf3">Serp</tspan><tspan fill="#4fd1c5">Ent</tspan></text>')
    body += (f'<text x="{tx:.0f}" y="{ty + fs2 * 1.5:.0f}" font-family="{f}" font-size="{fs2}" fill="#8b9cad">'
             f'One key. Many SERP accounts. Zero wasted credits.</text>')
    sm = 0.5 if big else 0.34
    sx = tx
    sy = ty + fs2 * 1.5 + (44 if big else 22)
    if big:
        body += mark_group(CHARMER.replace('id="g"', 'id="g2"').replace("url(#g)", "url(#g2)"), sx, sy, sm)
    gx = sx + (256 * sm + 16 if big else 0)
    gy = sy + (256 * sm * 0.62 if big else 14)
    body += (f'<text x="{gx:.0f}" y="{gy:.0f}" font-family="{f}" font-size="{fs2 * 0.85:.0f}" '
             f'fill="#e6edf3">with <tspan font-weight="700" fill="#7c9cff">Snake Charmer</tspan> &#8212; the control UI</text>')
    return svg(body, w, h, DARK)

write("social-card.svg", card(1280, 640, True))
write("banner.svg", card(1000, 260, False))
print("ok")

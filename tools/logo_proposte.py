"""Genera tre proposte di logo (serpente farmacista in stile 3D) in frontend/logo-proposte/.

    python tools/logo_proposte.py
"""

from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "frontend" / "logo-proposte"

PALETTES = {  # pelle: luce, medio, ombra, riflesso
    "verde": ("#c8f78e", "#6fcb4f", "#2b8438", "#d2fa9e"),
    "smeraldo": ("#a8f2cf", "#2fb886", "#12705a", "#c9fbe3"),
    "lime": ("#e6fb9a", "#9bd63c", "#4f8f1f", "#f2ffc4"),
}
PAL = dict(zip(("light", "mid", "dark", "shine"), PALETTES["verde"]))

EYES = {  # iride: chiaro, medio, scuro
    "azzurri": ("#9fe0ff", "#2a86e0", "#0b3474"),
    "ambra": ("#ffd98a", "#d98a1e", "#6b3a08"),
    "scuri": ("#7a6a62", "#2a211d", "#050404"),
}


def defs(bg_top, bg_bottom):
    return f"""<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{bg_top}"/><stop offset="1" stop-color="{bg_bottom}"/></linearGradient>
  <radialGradient id="glow" cx=".5" cy=".42" r=".55"><stop offset="0" stop-color="#fff" stop-opacity=".85"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>
  <radialGradient id="skin" cx=".5" cy=".45" r=".62" fx=".36" fy=".26"><stop offset="0" stop-color="{PAL['light']}"/><stop offset=".45" stop-color="{PAL['mid']}"/><stop offset="1" stop-color="{PAL['dark']}"/></radialGradient>
  <linearGradient id="skinV" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{PAL['dark']}"/><stop offset=".35" stop-color="{PAL['light']}"/><stop offset=".65" stop-color="{PAL['mid']}"/><stop offset="1" stop-color="{PAL['dark']}"/></linearGradient>
  <radialGradient id="belly" cx=".5" cy=".4" r=".65" fx=".4" fy=".3"><stop offset="0" stop-color="#fff8dc"/><stop offset=".6" stop-color="#f5d78f"/><stop offset="1" stop-color="#d6a24c"/></radialGradient>
  <linearGradient id="bellyV" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#d9a64f"/><stop offset=".4" stop-color="#fff3cf"/><stop offset=".7" stop-color="#f3d389"/><stop offset="1" stop-color="#cf9a43"/></linearGradient>
  <radialGradient id="sclera" cx=".45" cy=".35" r=".7"><stop offset="0" stop-color="#ffffff"/><stop offset=".8" stop-color="#eef3f8"/><stop offset="1" stop-color="#c9d4df"/></radialGradient>
  <linearGradient id="coat" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#cfdbe1"/><stop offset=".3" stop-color="#ffffff"/><stop offset=".7" stop-color="#f5f9fb"/><stop offset="1" stop-color="#c3d1d8"/></linearGradient>
  <linearGradient id="dark" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#6b7684"/><stop offset=".5" stop-color="#363e49"/><stop offset="1" stop-color="#1c2129"/></linearGradient>
  <linearGradient id="metal" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#f4f6f8"/><stop offset=".5" stop-color="#c9d0d7"/><stop offset="1" stop-color="#9aa4ae"/></linearGradient>
  <linearGradient id="cross" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#6ff0a0"/><stop offset=".55" stop-color="#22c26a"/><stop offset="1" stop-color="#128a4a"/></linearGradient>
  <linearGradient id="screen" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#e3f8ff"/><stop offset="1" stop-color="#8fd8f2"/></linearGradient>
  <linearGradient id="deskTop" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#7fd0da"/><stop offset="1" stop-color="#3ea4b3"/></linearGradient>
  <linearGradient id="deskFront" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2f8f9d"/><stop offset="1" stop-color="#1d6a78"/></linearGradient>
  <filter id="b2" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="2"/></filter>
  <filter id="b4" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="4"/></filter>
  <filter id="b8" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="8"/></filter>
  <filter id="shadow" x="-30%" y="-30%" width="160%" height="160%">
    <feGaussianBlur in="SourceAlpha" stdDeviation="9"/><feOffset dy="10"/>
    <feComponentTransfer><feFuncA type="linear" slope=".28"/></feComponentTransfer>
    <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
  <clipPath id="tile"><rect x="16" y="16" width="480" height="480" rx="112"/></clipPath>
</defs>"""


def eye(x, look, colors):
    light, mid, deep = colors
    gid = f"iris{abs(hash((x, colors))) % 10**6}"
    lx, ly = look
    return f"""<radialGradient id="{gid}" cx=".5" cy=".65" r=".6"><stop offset="0" stop-color="{light}"/><stop offset=".55" stop-color="{mid}"/><stop offset="1" stop-color="{deep}"/></radialGradient>
<g transform="translate({x} -20)">
  <ellipse cx="0" cy="4" rx="42" ry="48" fill="#1f5a2b" opacity=".35" filter="url(#b4)"/>
  <ellipse cx="0" cy="0" rx="40" ry="47" fill="url(#sclera)"/>
  <ellipse cx="{lx}" cy="{6 + ly}" rx="30" ry="35" fill="url(#{gid})"/>
  <ellipse cx="{lx + 1}" cy="{10 + ly}" rx="15" ry="18" fill="#05070d"/>
  <ellipse cx="{lx - 9}" cy="{-6 + ly}" rx="11" ry="12" fill="#fff"/>
  <circle cx="{lx + 12}" cy="{22 + ly}" r="5" fill="#fff" opacity=".85"/>
  <path d="M-39 -10 A40 47 0 0 1 39 -10" fill="none" stroke="#173f20" stroke-width="6" stroke-linecap="round"/>
  <path d="M{36 if x > 0 else -36} -22 l{9 if x > 0 else -9} -9" stroke="#173f20" stroke-width="5" stroke-linecap="round"/>
</g>"""


def head(eyes="azzurri", look=(4, 0)):
    """Testa centrata in 0,0: circa 250 x 210."""
    c = EYES[eyes]
    return f"""<g>
  <ellipse cx="0" cy="8" rx="128" ry="102" fill="#14401d" opacity=".3" filter="url(#b8)"/>
  <ellipse cx="0" cy="0" rx="126" ry="100" fill="url(#skin)"/>
  <ellipse cx="-42" cy="-60" rx="62" ry="24" fill="#fff" opacity=".38" filter="url(#b4)"/>
  <ellipse cx="0" cy="62" rx="96" ry="50" fill="url(#belly)"/>
  <ellipse cx="-22" cy="44" rx="42" ry="12" fill="#fff" opacity=".55" filter="url(#b4)"/>
  <ellipse cx="-17" cy="44" rx="6" ry="4.5" fill="#7a5524" opacity=".75"/>
  <ellipse cx="17" cy="44" rx="6" ry="4.5" fill="#7a5524" opacity=".75"/>
  <path d="M-30 76 Q0 96 30 76" fill="none" stroke="#5a3712" stroke-width="6" stroke-linecap="round"/>
  <path d="M-34 72 q-4 4 -1 9 M34 72 q4 4 1 9" fill="none" stroke="#5a3712" stroke-width="4" stroke-linecap="round"/>
  <ellipse cx="-80" cy="40" rx="20" ry="12" fill="#ff7f86" opacity=".55" filter="url(#b2)"/>
  <ellipse cx="80" cy="40" rx="20" ry="12" fill="#ff7f86" opacity=".55" filter="url(#b2)"/>
  {eye(-50, look, c)}
  {eye(50, look, c)}
</g>"""


def headset():
    """Cuffia con microfono, nelle coordinate della testa."""
    return """<g>
  <path d="M-134 -2 C-136 -146 136 -146 134 -2" fill="none" stroke="url(#dark)" stroke-width="15" stroke-linecap="round"/>
  <path d="M-118 -46 C-96 -118 96 -118 118 -46" fill="none" stroke="#a9b4c1" stroke-width="3" stroke-linecap="round" opacity=".7"/>
  <rect x="-156" y="-42" width="36" height="74" rx="17" fill="url(#dark)"/>
  <rect x="120" y="-42" width="36" height="74" rx="17" fill="url(#dark)"/>
  <rect x="-150" y="-34" width="8" height="40" rx="4" fill="#9aa6b4" opacity=".6"/>
  <rect x="126" y="-34" width="8" height="40" rx="4" fill="#9aa6b4" opacity=".6"/>
  <path d="M-140 28 Q-130 110 -62 108" fill="none" stroke="#2c333d" stroke-width="8" stroke-linecap="round"/>
  <ellipse cx="-54" cy="108" rx="15" ry="12" fill="url(#dark)"/>
  <ellipse cx="-58" cy="104" rx="5" ry="3" fill="#c3ccd6" opacity=".8"/>
</g>"""


def coat(badge=True):
    """Camice con collo e pancia; spalle in y=0, centro x=0, alto circa 210."""
    badge_svg = """<g transform="translate(-66 112)">
      <rect x="-18" y="-18" width="36" height="36" rx="9" fill="#fff" stroke="#d3dde2" stroke-width="2"/>
      <path d="M-5 -12h10v7h7v10h-7v7h-10v-7h-7v-10h7z" fill="url(#cross)"/>
    </g>""" if badge else ""
    return f"""<g>
  <rect x="-40" y="-70" width="80" height="150" rx="34" fill="url(#skinV)"/>
  <path d="M-120 230 L-110 66 Q-102 12 -48 4 L48 4 Q102 12 110 66 L120 230 Z" fill="url(#coat)"/>
  <path d="M-46 4 L0 96 L46 4 Z" fill="url(#bellyV)"/>
  <path d="M-30 22h60 M-22 42h44 M-14 62h28 M-7 80h14" stroke="#c48f3e" stroke-width="3" opacity=".6"/>
  <path d="M-46 4 L-74 56 L-38 60 L0 96 Z" fill="#ffffff"/>
  <path d="M46 4 L74 56 L38 60 L0 96 Z" fill="#eef4f6"/>
  <path d="M-38 60 L0 96 L38 60" fill="none" stroke="#aebcc4" stroke-width="3" opacity=".7"/>
  <path d="M0 96 V230" stroke="#c7d3d9" stroke-width="4"/>
  <circle cx="10" cy="128" r="6" fill="url(#metal)"/><circle cx="10" cy="170" r="6" fill="url(#metal)"/>
  <rect x="38" y="104" width="44" height="38" rx="7" fill="#f2f7f9" stroke="#cdd8de" stroke-width="2"/>
  <rect x="50" y="82" width="8" height="30" rx="4" fill="#3a7bd5"/><rect x="50" y="82" width="8" height="8" rx="4" fill="#9cc2f5"/>
  {badge_svg}
</g>"""


def tube(d, w=54, belly=True):
    """Corpo a tubo con volume: pancia crema sotto, verde, riflesso sopra."""
    out = []
    if belly:
        out.append(f'<path d="{d}" fill="none" stroke="url(#bellyV)" stroke-width="{w * .42}" transform="translate(0 {w * .46})" stroke-linecap="round"/>')
        out.append(f'<path d="{d}" fill="none" stroke="#c48f3e" stroke-width="{w * .42}" stroke-dasharray="2.5 13" transform="translate(0 {w * .46})" opacity=".7"/>')
    out.append(f'<path d="{d}" fill="none" stroke="{PAL['dark']}" stroke-width="{w}" stroke-linecap="round"/>')
    out.append(f'<path d="{d}" fill="none" stroke="{PAL['mid']}" stroke-width="{w * .74}" transform="translate(0 {-w * .1})" stroke-linecap="round"/>')
    out.append(f'<path d="{d}" fill="none" stroke="{PAL['shine']}" stroke-width="{w * .2}" transform="translate(0 {-w * .3})" stroke-linecap="round" opacity=".8" filter="url(#b2)"/>')
    return "\n".join(out)


def tail(p0, p1, p2, p3, w0, w1=6, steps=28):
    """Coda che si assottiglia lungo una curva di Bézier: pancia crema, verde, riflesso."""
    import math

    def point(t):
        a = [(1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t * t, t ** 3]
        return (sum(k * p[0] for k, p in zip(a, (p0, p1, p2, p3))), sum(k * p[1] for k, p in zip(a, (p0, p1, p2, p3))))

    pts = [point(i / steps) for i in range(steps + 1)]
    # lato "alto" (luce) e lato "basso" (ombra/pancia) della coda, scelti per y media
    side_a, side_b = [], []
    for i, (x, y) in enumerate(pts):
        nx, ny = pts[min(i + 1, steps)][0] - pts[max(i - 1, 0)][0], pts[min(i + 1, steps)][1] - pts[max(i - 1, 0)][1]
        length = math.hypot(nx, ny) or 1
        w = (w0 + (w1 - w0) * (i / steps) ** 1.3) / 2
        ox, oy = -ny / length * w, nx / length * w
        side_a.append((x + ox, y + oy, w))
        side_b.append((x - ox, y - oy, w))
    if sum(p[1] for p in side_a) > sum(p[1] for p in side_b):
        side_a, side_b = side_b, side_a
    top, bottom = side_a, side_b
    poly = lambda seq: " ".join(f"{p[0]:.1f},{p[1]:.1f}" for p in seq)
    outline = poly(top + bottom[::-1])
    belly = poly([(x, y + w * .5) for x, y, w in bottom] + [(c[0], c[1] + w * .1) for c, (_, _, w) in zip(pts, bottom)][::-1])
    mid = poly([(x, y + w * .15) for x, y, w in top] + [(x + (cx - x) * .3, y + (cy - y) * .3) for (x, y, _), (cx, cy) in zip(bottom, pts)][::-1])
    shine = poly([(cx + (x - cx) * .55, cy + (y - cy) * .55) for (x, y, _), (cx, cy) in zip(top, pts)][: int(steps * .85)])
    return f"""<g>
  <polygon points="{belly}" fill="url(#bellyV)"/>
  <polygon points="{outline}" fill="{PAL['dark']}"/>
  <polygon points="{mid}" fill="{PAL['mid']}"/>
  <polyline points="{shine}" fill="none" stroke="{PAL['shine']}" stroke-width="{w0 * .16:.1f}" stroke-linecap="round" opacity=".8" filter="url(#b2)"/>
</g>"""


def big_cross(x, y, s=1.0):
    return f"""<g transform="translate({x} {y}) scale({s})" filter="url(#shadow)">
  <path d="M-22 -66h44v44h44v44h-44v44h-44v-44h-44v-44h44z" fill="url(#cross)"/>
  <path d="M-12 -56h12v40" fill="none" stroke="#c9ffe0" stroke-width="7" stroke-linecap="round" opacity=".75" filter="url(#b2)"/>
</g>"""


def wave(x, y, color="#22c26a"):
    bars = [(0, 14), (14, 34), (28, 54), (42, 26), (56, 44), (70, 18), (84, 8)]
    return "".join(f'<rect x="{x + dx}" y="{y - h / 2}" width="9" height="{h}" rx="4.5" fill="{color}"/>' for dx, h in bars)


def tile(content, bg):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
{defs(*bg)}
<g clip-path="url(#tile)">
  <rect x="0" y="0" width="512" height="512" fill="url(#bg)"/>
  <ellipse cx="240" cy="210" rx="250" ry="220" fill="url(#glow)"/>
  {content}
</g>
<rect x="16" y="16" width="480" height="480" rx="112" fill="none" stroke="#000" stroke-opacity=".08" stroke-width="4"/>
</svg>
"""


def proposta_banco():
    """1 · Al banco: arrotolato sul banco, camice e cuffia, portatile accanto."""
    desk = """<rect x="0" y="404" width="512" height="34" fill="url(#deskTop)"/>
  <rect x="0" y="436" width="512" height="80" fill="url(#deskFront)"/>
  <rect x="0" y="434" width="512" height="4" fill="#ffffff" opacity=".35"/>"""
    laptop = f"""<g filter="url(#shadow)">
    <path d="M372 300 h116 a8 8 0 0 1 8 8 v86 h-132 v-86 a8 8 0 0 1 8 -8z" fill="url(#dark)"/>
    <rect x="374" y="310" width="112" height="80" rx="5" fill="url(#screen)"/>
    {wave(390, 350)}
    <path d="M352 396 h164 l-10 16 h-144z" fill="url(#metal)"/>
  </g>"""
    return tile(f"""
  {big_cross(424, 110, .9)}
  {laptop}
  {tube("M70 384 A148 34 0 0 1 366 384", 40, belly=False)}
  <g transform="translate(218 262) scale(.86)" filter="url(#shadow)">{coat()}</g>
  {desk}
  <ellipse cx="220" cy="432" rx="160" ry="14" fill="#0d3b44" opacity=".35" filter="url(#b8)"/>
  {tube("M76 396 A146 30 0 0 0 368 396", 52)}
  {tube("M116 370 A104 22 0 0 0 324 370", 46)}
  {tail((250, 424), (330, 440), (400, 438), (432, 404), 44, 6)}
  <g transform="translate(218 158) scale(.84)">{head("azzurri", (6, 2))}{headset()}</g>
""", ("#eafaf1", "#bfe9d3"))


def proposta_ritratto():
    """2 · Ritratto: primo piano dietro un portatile con la croce sul coperchio."""
    laptop = """<g filter="url(#shadow)">
    <path d="M128 396 h256 a14 14 0 0 1 14 14 v110 h-284 v-110 a14 14 0 0 1 14 -14z" fill="url(#metal)"/>
    <path d="M128 396 h256 a14 14 0 0 1 14 14 v8 h-284 v-8 a14 14 0 0 1 14 -14z" fill="#ffffff" opacity=".6"/>
    <circle cx="256" cy="462" r="34" fill="#ffffff" opacity=".5" filter="url(#b8)"/>
    <path d="M248 438h16v16h16v16h-16v16h-16v-16h-16v-16h16z" fill="url(#cross)"/>
  </g>"""
    return tile(f"""
  <path d="M226 40h60v110h110v60h-110v110h-60v-110h-110v-60h110z" fill="#ffffff" opacity=".35"/>
  <g transform="translate(256 318) scale(1.22)" filter="url(#shadow)">{coat()}</g>
  {tail((384, 520), (490, 450), (392, 372), (452, 318), 44, 6)}
  {laptop}
  <g transform="translate(256 196) scale(1.04)">{head("ambra", (0, 4))}{headset()}</g>
""", ("#e4f6ff", "#9fd6ee"))


def proposta_cobra():
    """3 · Cobra: cappuccio, camice, microfono da studio e monitor."""
    hood = """<g>
    <path d="M-60 -78 C-128 -70 -186 -8 -190 66 C-194 128 -146 172 -60 204 L60 204 C146 172 194 128 190 66 C186 -8 128 -70 60 -78 Z" fill="url(#skin)" stroke="#2a7d36" stroke-width="4" filter="url(#shadow)"/>
    <path d="M-124 -24 C-176 20 -180 104 -124 150 C-146 100 -146 30 -112 -10 Z" fill="url(#bellyV)"/>
    <path d="M124 -24 C176 20 180 104 124 150 C146 100 146 30 112 -10 Z" fill="url(#bellyV)"/>
    <path d="M-150 30 h22 M-156 62 h26 M-152 94 h24 M150 30 h-22 M156 62 h-26 M152 94 h-24" stroke="#c48f3e" stroke-width="3" opacity=".6"/>
  </g>"""
    mic = f"""<g filter="url(#shadow)">
    <ellipse cx="88" cy="414" rx="44" ry="11" fill="url(#dark)"/>
    <rect x="83" y="330" width="10" height="84" rx="5" fill="url(#metal)"/>
    <path d="M70 336 h36 v12 a18 18 0 0 1 -36 0z" fill="url(#dark)"/>
    <rect x="64" y="246" width="48" height="92" rx="24" fill="url(#dark)"/>
    <path d="M70 266 h36 M68 282 h40 M68 298 h40 M70 314 h36" stroke="#8c97a4" stroke-width="3" opacity=".7"/>
    <rect x="72" y="252" width="9" height="56" rx="4.5" fill="#ffffff" opacity=".25"/>
  </g>"""
    monitor = f"""<g filter="url(#shadow)">
    <rect x="420" y="372" width="22" height="36" fill="url(#metal)"/>
    <rect x="398" y="402" width="66" height="12" rx="6" fill="url(#metal)"/>
    <rect x="366" y="262" width="132" height="112" rx="12" fill="url(#dark)"/>
    <rect x="376" y="272" width="112" height="90" rx="6" fill="url(#screen)"/>
    {wave(388, 318)}
  </g>"""
    desk = """<rect x="0" y="410" width="512" height="30" fill="#f6d9a8"/>
  <rect x="0" y="438" width="512" height="80" fill="#e2a964"/>
  <rect x="0" y="436" width="512" height="4" fill="#fff" opacity=".4"/>"""
    return tile(f"""
  {big_cross(430, 112, .62)}
  <g transform="translate(240 196)">{hood}</g>
  <g transform="translate(240 300) scale(.95)" filter="url(#shadow)">{coat()}</g>
  {monitor}
  {desk}
  {mic}
  <g transform="translate(240 196) scale(.92)">{head("scuri", (-4, 2))}</g>
""", ("#fff6e6", "#ffd8a6"))


def snake_eye(x, look, colors, size=1.0):
    light, mid, deep = colors
    gid = f"siris{'r' if x > 0 else 'l'}"
    lx, ly = look
    side = 1 if x > 0 else -1
    return f"""<radialGradient id="{gid}" cx=".5" cy=".65" r=".6"><stop offset="0" stop-color="{light}"/><stop offset=".55" stop-color="{mid}"/><stop offset="1" stop-color="{deep}"/></radialGradient>
<g transform="translate({x} -22) scale({size})">
  <ellipse cx="0" cy="5" rx="40" ry="44" fill="#0d3b1c" opacity=".35" filter="url(#b4)"/>
  <ellipse cx="0" cy="0" rx="37" ry="42" fill="url(#sclera)"/>
  <ellipse cx="{lx}" cy="{6 + ly}" rx="28" ry="32" fill="url(#{gid})"/>
  <ellipse cx="{lx + 1}" cy="{9 + ly}" rx="10" ry="19" fill="#05070d"/>
  <ellipse cx="{lx - 9}" cy="{-6 + ly}" rx="10" ry="11" fill="#fff"/>
  <circle cx="{lx + 11}" cy="{20 + ly}" r="4.5" fill="#fff" opacity=".85"/>
  <path d="M-37 -6 A37 42 0 0 1 37 -6" fill="none" stroke="#123a1c" stroke-width="6" stroke-linecap="round"/>
  <path d="M{side * 33} -20 l{side * 10} -8 M{side * 24} -31 l{side * 7} -10" stroke="#123a1c" stroke-width="4.5" stroke-linecap="round"/>
</g>"""


def snake_head(eyes="ambra", look=(3, 2), pattern=True, glasses=False):
    """Testa da serpente vista di fronte: larga sopra, muso arrotondato e stretto, bocca lunga."""
    c = EYES[eyes]
    outline = ("M0 -100 C92 -100 138 -50 134 0 C130 50 98 84 72 110 C56 128 32 142 0 142 "
               "C-32 142 -56 128 -72 110 C-98 84 -130 50 -134 0 C-138 -50 -92 -100 0 -100 Z")
    scales = """<g fill="{dark}" opacity=".22">
    <path d="M0 -92 l16 18 l-16 18 l-16 -18z"/>
    <path d="M-30 -74 l13 15 l-13 15 l-13 -15z"/><path d="M30 -74 l13 15 l-13 15 l-13 -15z"/>
    <path d="M0 -50 l11 13 l-11 13 l-11 -13z"/>
    <circle cx="-104" cy="-20" r="7"/><circle cx="-116" cy="4" r="6"/><circle cx="104" cy="-20" r="7"/><circle cx="116" cy="4" r="6"/>
  </g>""".format(dark=PAL["dark"]) if pattern else ""
    specs = f"""<g fill="#ffffff" fill-opacity=".14" stroke="#3a2a22" stroke-width="5">
    <circle cx="-60" cy="-21" r="44"/><circle cx="60" cy="-21" r="44"/>
  </g>
  <path d="M-16 -26 Q0 -36 16 -26" fill="none" stroke="#3a2a22" stroke-width="5" stroke-linecap="round"/>
  <path d="M-104 -26 L-130 -32 M104 -26 L130 -32" stroke="#3a2a22" stroke-width="5" stroke-linecap="round"/>
  <path d="M-80 -52 q14 -10 28 -8 M28 -60 q14 -2 28 8" fill="none" stroke="#fff" stroke-width="5" stroke-linecap="round" opacity=".7"/>""" if glasses else ""
    return f"""<g>
  <clipPath id="headclip"><path d="{outline}"/></clipPath>
  <path d="{outline}" transform="translate(0 10)" fill="#0f3a1a" opacity=".3" filter="url(#b8)"/>
  <path d="{outline}" fill="url(#skin)"/>
  <g clip-path="url(#headclip)">
    <ellipse cx="0" cy="84" rx="64" ry="52" fill="{PAL['light']}" opacity=".55" filter="url(#b8)"/>
    <path d="M-150 100 Q0 152 150 100 L150 170 L-150 170 Z" fill="url(#belly)"/>
  </g>
  {scales}
  <ellipse cx="-44" cy="-66" rx="58" ry="20" fill="#fff" opacity=".35" filter="url(#b4)"/>
  <ellipse cx="0" cy="72" rx="34" ry="16" fill="#fff" opacity=".35" filter="url(#b4)"/>
  <path d="M-11 92 q-4 -5 -8 1 M11 92 q4 -5 8 1" fill="none" stroke="#123a1c" stroke-width="4.5" stroke-linecap="round"/>
  <path d="M-60 104 Q0 138 60 104" fill="none" stroke="#123a1c" stroke-width="5.5" stroke-linecap="round"/>
  <path d="M-60 104 q-7 -2 -9 -10 M60 104 q7 -2 9 -10" fill="none" stroke="#123a1c" stroke-width="4.5" stroke-linecap="round"/>
  <ellipse cx="-88" cy="52" rx="17" ry="10" fill="#ff9ebd" opacity=".8" filter="url(#b2)"/>
  <ellipse cx="88" cy="52" rx="17" ry="10" fill="#ff9ebd" opacity=".8" filter="url(#b2)"/>
  {snake_eye(-60, look, c, .92)}
  {snake_eye(60, look, c, .92)}
  {specs}
</g>"""


def ritratto(eyes, palette, bg, glasses=False, pattern=True, look=(3, 2), lid_color=None):
    """Composizione del ritratto: camice, coda, portatile con croce, testa da serpente con cuffia."""
    PAL.update(zip(("light", "mid", "dark", "shine"), PALETTES[palette]))
    lid = lid_color or "url(#metal)"
    laptop = f"""<g filter="url(#shadow)">
    <path d="M128 396 h256 a14 14 0 0 1 14 14 v110 h-284 v-110 a14 14 0 0 1 14 -14z" fill="{lid}"/>
    <path d="M128 396 h256 a14 14 0 0 1 14 14 v8 h-284 v-8 a14 14 0 0 1 14 -14z" fill="#ffffff" opacity=".55"/>
    <circle cx="256" cy="462" r="34" fill="#ffffff" opacity=".5" filter="url(#b8)"/>
    <path d="M248 438h16v16h16v16h-16v16h-16v-16h-16v-16h16z" fill="url(#cross)"/>
  </g>"""
    return tile(f"""
  <path d="M226 40h60v110h110v60h-110v110h-60v-110h-110v-60h110z" fill="#ffffff" opacity=".35"/>
  <g transform="translate(256 322) scale(1.2)" filter="url(#shadow)">{coat()}</g>
  {tail((384, 520), (490, 450), (392, 372), (452, 318), 44, 6)}
  {laptop}
  <g transform="translate(256 196) scale(1.0)">{snake_head(eyes, look, pattern, glasses)}{headset()}</g>
""", bg)


APP = {  # colori di frontend/desk.css
    "accento": "#145a48", "testo": "#142b27", "sfondo": "#f0f5f1", "menta": "#c8eddb", "giallo": "#fae4a0",
}
PALETTES["banco"] = ("#c2f3d6", "#4cb087", APP["accento"], "#e2fbed")


def logo_app():
    """Logo ufficiale: proposta A (classico) con i colori del frontend del banco."""
    svg = ritratto("ambra", "banco", ("#f6fbf8", APP["menta"]))
    swaps = {
        # croce: dal verde brillante al verde dell'app
        '<stop offset="0" stop-color="#6ff0a0"/><stop offset=".55" stop-color="#22c26a"/><stop offset="1" stop-color="#128a4a"/>':
            f'<stop offset="0" stop-color="#7fdcae"/><stop offset=".55" stop-color="#2e9a70"/><stop offset="1" stop-color="{APP["accento"]}"/>',
        # pancia: verso il giallo delle evidenziazioni
        '<stop offset="0" stop-color="#fff8dc"/><stop offset=".6" stop-color="#f5d78f"/><stop offset="1" stop-color="#d6a24c"/>':
            f'<stop offset="0" stop-color="#fffaf0"/><stop offset=".6" stop-color="{APP["giallo"]}"/><stop offset="1" stop-color="#d9ab55"/>',
        '<stop offset="0" stop-color="#d9a64f"/><stop offset=".4" stop-color="#fff3cf"/><stop offset=".7" stop-color="#f3d389"/><stop offset="1" stop-color="#cf9a43"/>':
            f'<stop offset="0" stop-color="#d9ab55"/><stop offset=".4" stop-color="#fffaf0"/><stop offset=".7" stop-color="{APP["giallo"]}"/><stop offset="1" stop-color="#cf9f4a"/>',
        # cuffia: grigio verdastro come il testo dell'app
        '<stop offset="0" stop-color="#6b7684"/><stop offset=".5" stop-color="#363e49"/><stop offset="1" stop-color="#1c2129"/>':
            f'<stop offset="0" stop-color="#6e8780"/><stop offset=".5" stop-color="#2f4741"/><stop offset="1" stop-color="{APP["testo"]}"/>',
        "#123a1c": APP["testo"], "#2c333d": "#23403a",
    }
    for old, new in swaps.items():
        assert old in svg, old[:40]
        svg = svg.replace(old, new)
    return svg.replace('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">',
                       '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" role="img" aria-label="Sales Agents: serpente farmacista al banco">', 1)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    logo = OUT.parent / "logo.svg"
    logo.write_text(logo_app(), encoding="utf-8")
    print(logo)
    proposte = (
        ("A-classico", lambda: ritratto("ambra", "verde", ("#e4f6ff", "#9fd6ee"))),
        ("B-occhiali", lambda: ritratto("azzurri", "smeraldo", ("#eafaf1", "#b6e8d0"), glasses=True, look=(2, 4))),
        ("C-lime", lambda: ritratto("scuri", "lime", ("#fffbea", "#ffe3a3"), pattern=True, look=(-3, 3), lid_color="#ffffff")),
    )
    for name, build in proposte:
        (OUT / f"{name}.svg").write_text(build(), encoding="utf-8")
        print(OUT / f"{name}.svg")


if __name__ == "__main__":
    main()

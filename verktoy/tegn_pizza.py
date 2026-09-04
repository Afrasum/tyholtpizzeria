"""Genererer pizzategningene til app/templates/_symboler.html.

Kjor:  uv run python verktoy/tegn_pizza.py

Genererer de to pizzategningene.

Revet ost og strimlet skinke er hundrevis av smaa strak. Det skal ikke
haandskrives — det skal genereres en gang, med fast froe, og resultatet
sjekkes inn som vanlig SVG. Ingen JS, ingen runtime-kostnad.

Hvert strak er en <line> med runde ender: det gir en kapselform med ett
element, som er den billigste maaten aa tegne en osteflis paa.
"""

import math
import random

R_SAUS = 180          # sausflaten
R_TRYGG = 168         # strak legges innenfor denne, saa ingenting stikker ut
MIDT = 250

OST = ["#F2D291", "#F8E4B6", "#DCAE5C"]      # tre nyanser = en haug, ikke en flate
OST_VEKT = [0.5, 0.28, 0.22]
SKINKE = ["#E3846F", "#F0B3A3", "#C55F4B"]
SKINKE_VEKT = [0.5, 0.27, 0.23]


def rutenett(steg, jitter, radius):
    """Jittret rutenett i sirkelen.

    Rent tilfeldige punkt klumper seg og etterlater hull. Et rutenett med
    stoy paa hvert punkt gir jevn dekning og ser likevel tilfeldig ut.
    """
    ut = []
    n = int(radius * 2 / steg) + 2
    start = MIDT - n * steg / 2
    for i in range(n):
        for j in range(n):
            x = start + i * steg + random.uniform(-jitter, jitter)
            y = start + j * steg + random.uniform(-jitter, jitter)
            if math.hypot(x - MIDT, y - MIDT) <= radius:
                ut.append((x, y))
    random.shuffle(ut)
    return ut


def strak(punkter, lengde, bredde, farger, vekter, opacity=None):
    linjer = []
    for x, y in punkter:
        v = random.uniform(0, math.pi)
        L = random.uniform(*lengde) / 2
        dx, dy = math.cos(v) * L, math.sin(v) * L
        # Hold hele straket innenfor sausen.
        if (math.hypot(x + dx - MIDT, y + dy - MIDT) > R_TRYGG
                or math.hypot(x - dx - MIDT, y - dy - MIDT) > R_TRYGG):
            continue
        f = random.choices(farger, weights=vekter)[0]
        b = round(random.uniform(*bredde), 1)
        o = f' opacity="{round(random.uniform(*opacity), 2)}"' if opacity else ""
        linjer.append(
            f'<line x1="{x-dx:.0f}" y1="{y-dy:.0f}" x2="{x+dx:.0f}" y2="{y+dy:.0f}"'
            f' stroke="{f}" stroke-width="{b}" stroke-linecap="round"{o}/>'
        )
    return linjer


BUNN = (
    '<circle cx="250" cy="250" r="205" fill="#E8D3A8" stroke="#B8955E" stroke-width="4"/>\n'
    '      <circle cx="250" cy="250" r="180" fill="#C63A2A"/>'
)

BASILIKUM = [
    'M220 220 Q205 200,227 195 Q245 210,230 232 Z',
    'M295 235 Q280 215,302 210 Q320 225,305 247 Z',
    'M230 315 Q213 297,236 291 Q254 305,240 327 Z',
    'M175 330 Q160 310,182 305 Q200 320,185 342 Z',
    'M168 235 Q153 215,175 210 Q193 225,178 247 Z',
]


def innrykk(linjer, n=6):
    pad = " " * n
    return ("\n" + pad).join(linjer)


def margherita():
    random.seed(20260904)
    # To lag: et tynt underlag som demper sausen, og flisene oppaa.
    under = strak(rutenett(25, 10, R_TRYGG), (22, 38), (11, 16), OST, OST_VEKT,
                  opacity=(.55, .8))
    over = strak(rutenett(29, 12, R_TRYGG - 6), (26, 46), (13, 18), OST, OST_VEKT)
    blad = [f'<path d="{d}" fill="#4F6A2E"/>' for d in BASILIKUM]
    return (
        '    <symbol id="pizza-margherita" viewBox="0 0 500 500">\n'
        f'      {BUNN}\n'
        '      {# Revet ost: mange smaa flis med sausen synlig imellom. #}\n'
        f'      {innrykk(under + over)}\n'
        f'      {innrykk(blad)}\n'
        '    </symbol>'
    )


def skinke():
    random.seed(4092026)
    # Samme ostelag som margheritaen — det ER samme ost — men tynnere, saa
    # skinkestrimlene ovenpaa har noe aa ligge paa uten aa forsvinne.
    ost = strak(rutenett(28, 11, R_TRYGG), (22, 42), (12, 17), OST, OST_VEKT,
                opacity=(.7, .95))
    # Salattopping: lange, tynne strimler. Faerre og lengre enn osten, ellers
    # blir det bare mer ost i en annen farge.
    strimler = strak(rutenett(46, 18, R_TRYGG - 12), (76, 122), (8, 11),
                     SKINKE, SKINKE_VEKT)
    return (
        '    <symbol id="pizza-skinke" viewBox="0 0 500 500">\n'
        f'      {BUNN}\n'
        '      {# Ost under, strimlet skinke oppaa. Skinka er salattopping —\n'
        '         lange tynne strimler, ikke flak. #}\n'
        f'      {innrykk(ost)}\n'
        f'      {innrykk(strimler)}\n'
        '    </symbol>'
    )


if __name__ == "__main__":
    # Skriver de to <symbol>-blokkene til stdout. Lim dem inn i
    # app/templates/_symboler.html og erstatt de eksisterende.
    print(margherita())
    print()
    print(skinke())

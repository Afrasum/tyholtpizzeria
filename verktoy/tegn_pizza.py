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
import re

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

# Paereskivene. Den gamle gullfargen laa for naer osten, saa med ost paa
# pizzaen ville de to smeltet sammen. Loesningen er aa gaa BLEIKERE enn
# osten, ikke groennere — paerekjoett er lyst kremgult, og konturen er det
# som gjoer at skiva leser som en skive.
PAERESKIVER = [
    'M170 175 Q150 170,150 195 Q150 220,170 225 Q190 220,195 200 Q195 180,170 175 Z',
    'M330 165 Q310 160,310 185 Q310 210,330 215 Q350 210,355 190 Q355 170,330 165 Z',
    'M155 275 Q135 270,135 295 Q135 320,155 325 Q175 320,180 300 Q180 280,155 275 Z',
    'M345 275 Q325 270,325 295 Q325 320,345 325 Q365 320,370 300 Q370 280,345 275 Z',
    'M185 355 Q165 350,165 375 Q165 395,185 400 Q205 395,210 380 Q210 360,185 355 Z',
    'M315 355 Q295 350,295 375 Q295 395,315 400 Q335 395,340 380 Q340 360,315 355 Z',
    'M250 235 Q230 230,230 255 Q230 280,250 285 Q270 280,275 260 Q275 240,250 235 Z',
]

# Osten paa den hvite bunnen trenger mer tyngde: paa cremen forsvinner den
# lyseste nyansen helt, saa den er vektet ned.
OST_HVIT = ["#EFC57A", "#DFAF57", "#F6DB9F"]
OST_HVIT_VEKT = [0.48, 0.32, 0.20]


SKIVESKALA = 1.45     # paereskivene var for smaa til aa leses paa 96 px


def midtpunkt(d):
    """Grovt senter i en path: midt i omrisset av tallene i den."""
    tall = [float(t) for t in re.findall(r"-?\d+\.?\d*", d)]
    xs, ys = tall[0::2], tall[1::2]
    return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2


def innrykk(linjer, n=6):
    pad = " " * n
    return ("\n" + pad).join(linjer)


def margherita():
    random.seed(20260904)
    # To lag: et tynt underlag som demper sausen, og flisene oppaa.
    under = strak(rutenett(25, 10, R_TRYGG), (22, 38), (11, 16), OST, OST_VEKT,
                  opacity=(.55, .8))
    over = strak(rutenett(29, 12, R_TRYGG - 6), (26, 46), (13, 18), OST, OST_VEKT)
    return (
        '    <symbol id="pizza-margherita" viewBox="0 0 500 500">\n'
        f'      {BUNN}\n'
        '      {# Revet ost: mange smaa flis med sausen synlig imellom. #}\n'
        f'      {innrykk(under + over)}\n'
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


def paere():
    random.seed(542026)
    # Creme fraiche-bunn i stedet for saus, ellers samme ost som de to andre.
    # Litt tynnere lag: cremen skal fortsatt slaa gjennom, det er den som
    # gjoer at pizzaen leser som «hvit».
    ost = strak(rutenett(38, 14, R_TRYGG), (24, 42), (12, 17),
                OST_HVIT, OST_HVIT_VEKT, opacity=(.8, 1))
    # Skivene ligger OPPAA osten, med kontur saa de leser som skiver og ikke
    # som mer ost i en annen farge.
    # Skivene skaleres opp om sitt EGET senter, ikke om pizzasenteret — da
    # blir de stoerre uten aa vandre utover mot skorpa. Konturen deles paa
    # skalaen, ellers vokser den med.
    skiver = []
    for d in PAERESKIVER:
        cx, cy = midtpunkt(d)
        skiver.append(
            f'<path d="{d}" fill="#F7F0D6" stroke="#CDB88A"'
            f' stroke-width="{3.8 / SKIVESKALA:.1f}" stroke-linejoin="round"'
            f' transform="translate({cx:.0f} {cy:.0f}) scale({SKIVESKALA})'
            f' translate({-cx:.0f} {-cy:.0f})"/>'
        )
    return (
        '    <symbol id="pizza-paere" viewBox="0 0 500 500">\n'
        '      <circle cx="250" cy="250" r="205" fill="#E8D3A8" stroke="#B8955E" stroke-width="4"/>\n'
        '      <circle cx="250" cy="250" r="180" fill="#FBF3DC"/>\n'
        '      {# Revet ost ogsaa her — den staar i ingredienslista. #}\n'
        f'      {innrykk(ost)}\n'
        f'      {innrykk(skiver)}\n'
        '    </symbol>'
    )


if __name__ == "__main__":
    # Skriver de to <symbol>-blokkene til stdout. Lim dem inn i
    # app/templates/_symboler.html og erstatt de eksisterende.
    print(margherita())
    print()
    print(skinke())
    print()
    print(paere())

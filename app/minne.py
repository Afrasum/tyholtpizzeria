"""Helga i tall, frosset 4.–5. september 2026.

Dette er IKKE levende tellere, og skal ikke bli det. Tallene er regnet ut én
gang mot produksjonsbasen etter at vi stengte, og støpt inn her med vilje:

* `ordrer.solgte_pizzaer()` teller fra siste «Nullstill dagen». Ett trykk på
  den knappen, og et levende tall på forsida ville falt til null uten at
  noen skjønte hvorfor.
* En side som er et minne skal vise det samme i dag som om tre år.

Kilde: `SELECT ... FROM ordre JOIN ordrelinje` over alle rader som ikke er
`avbrutt` eller `forlatt` — 206 av 208 bestillinger. De to som falt ut var én
kunde som aldri kom, og én feilbestilling.

INGEN PERSONOPPLYSNINGER HER. Basen har 119 e-postadresser og 208 fornavn.
Ingenting av det skal ut på en offentlig side — bare summene.
"""

from __future__ import annotations

PIZZAER = 299
BESTILLINGER = 206
KRONER = PIZZAER * 59      # alt kostet 59 kr, så dette ER omsetningen

# Median, ikke snitt. Snittet er 8,3 og medianen 8,2 — de er like her, og da
# er medianen den ærligste av dem.
MEDIAN_MINUTTER = 8
TREGESTE_MINUTTER = 19     # ingen ventet mer enn tjue

# Datoene, som tekst, fordi de aldri skal regnes på igjen.
DATOER = "4.–5. september 2026"
STED = "Tyholtveien 25, Trondheim"

# Nummerserien: 47 til 257. Tre numre i mellom tilhørte prøvebestillinger som
# ble slettet før åpning, så serien er lengre enn antall rader. Derfor står
# den ikke som et tall på sida — den ville ikke gått opp for en leser.
FORSTE_NUMMER = 47
SISTE_NUMMER = 257

# Avsnittene under «Hvem vi er». Ett strengelement per avsnitt.
#
# Tom til noen skriver dem. Det er MED VILJE ikke en plassholdertekst i malen:
# en stiplet «ikke skrevet ennå»-rute på en side som ligger ute er verre enn
# ingen tekst. Er denne tom, hopper malen over avsnittene og lar den ene linja
# vi faktisk kan stå for bære seksjonen.
OM_OSS: tuple[str, ...] = ()

# (kallenavn, det ekte navnet, antall). Rekkefølge = slik de faktisk solgte.
RETTER = [
    ("Don Skinkone", "Skinke", 195),
    ("Pæreoni & Pérignon", "Hvit pizza med pære", 54),
    ("Marcus og Margherita", "Margherita", 50),
]

# Kveldene, ikke kalenderdøgnene: bestillingen som kom 00:06 natt til lørdag
# hører til fredagens kveld, og er talt der. Summen er fortsatt 299.
#
# `timer` er (klokketime, pizzaer). Hullene i serien er ekte — klokka 21 på
# fredag falt det til seks pizzaer før det tok seg opp igjen.
KVELDER = [
    {
        "navn": "Fredag 4. september",
        "fra": "15:31",
        "til": "00:06",
        "pizzaer": 142,
        "timer": [(15, 3), (16, 10), (17, 11), (18, 17), (19, 31),
                  (20, 26), (21, 6), (22, 21), (23, 14), (0, 3)],
    },
    {
        "navn": "Lørdag 5. september",
        "fra": "15:32",
        "til": "21:51",
        "pizzaer": 157,
        "timer": [(15, 2), (16, 15), (17, 40), (18, 49),
                  (19, 15), (20, 13), (21, 23)],
    },
]

# Toppen på grafen. Regnes ut framfor å skrives, så en rettelse i `KVELDER`
# ikke etterlater en søyle som stikker utenfor ruta.
TOPPTIME = max(n for kveld in KVELDER for _, n in kveld["timer"])
TOPPTIME_NAAR = "lørdag mellom 18 og 19"


def alt() -> dict:
    """Hele minnet som én malkontekst."""
    return {
        "om_oss": OM_OSS,
        "pizzaer": PIZZAER,
        "bestillinger": BESTILLINGER,
        "kroner": KRONER,
        "median_minutter": MEDIAN_MINUTTER,
        "tregeste_minutter": TREGESTE_MINUTTER,
        "datoer": DATOER,
        "sted": STED,
        "retter": RETTER,
        "kvelder": KVELDER,
        "topptime": TOPPTIME,
        "topptime_naar": TOPPTIME_NAAR,
    }

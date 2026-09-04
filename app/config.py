"""Konfigurasjon, lest fra miljøvariabler med fornuftige standardverdier.

Alt som skiller utvikling på Mac fra drift på rpi5 skal stå her, ikke spredt
utover modulene.
"""

from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

ROT = Path(__file__).resolve().parent.parent

# Databasen ligger bevisst UTENFOR git-treet. teller.db i falch-vaskebyra
# ligger inni arbeidstreet uten backup, og ordrer med kundeeposter fortjener
# bedre enn det.
DB_STI = Path(
    os.environ.get("TP_DB", Path.home() / "data" / "tyholtpizzeria" / "base.db")
)

# Ett passord, ingen adgangskontroll utover det. Settes i .env på Pi-en.
ADMIN_PASSORD = os.environ.get("TP_ADMIN_PASSORD", "bytt-meg")
HEMMELIG_NOKKEL = os.environ.get("TP_HEMMELIG_NOKKEL", "usikker-utviklingsnokkel")

# Printer. TP_PRINTER_PORT tom streng slår av printing helt, slik at appen kan
# kjøres på Mac uten Bluetooth.
PRINTER_PORT = os.environ.get("TP_PRINTER_PORT", "")
# labelmaker.py, IKKE printlabel.py: sistnevntes -i/--image er dodt i commit
# 27bb7bc (args.image brukes bare til aa hoppe over render-blokken, og da ryker
# "assert data is not None"). labelmaker.py kaller read_png() og virker.
LABELMAKER_STI = Path(
    os.environ.get("TP_LABELMAKER", ROT / "vendor" / "PT-P300BT" / "labelmaker.py")
)
# QR paa etiketten. Verifisert skannbar fra tape 3. september.
QR_PA_ETIKETT = os.environ.get("TP_QR_PA_ETIKETT", "1") == "1"
# Store bokstaver med vilje: da holder «HTTPS://...» seg i QR-kodens
# alfanumeriske modus (som har med : og / og A-Z), og koden blir versjon 2
# med 25x25 moduler i stedet for versjon 3 med 29x29. Samme fysiske stoerrelse,
# men 0,36 mm per modul framfor 0,31 - og det var forskjellen som gjorde at
# den lot seg skanne. Skjema og vertsnavn er ikke versalfoelsomme, saa
# telefonen aapner sida som normalt. Sma bokstaver ville tvunget byte-modus.
QR_URL = os.environ.get("TP_QR_URL", "HTTPS://TYHOLTPIZZERIA.COM")
# QR bare pa den forste etiketten i en ordre, framfor pa alle. QR-en koster
# 1,1 cm tape per etikett, sa en tre-pizza ordre sparer 2,2 cm. Avveiningen er
# deling: er QR-en bare pa en eske, er det bare den ene som kan deles videre.
QR_BARE_FORSTE = os.environ.get("TP_QR_BARE_FORSTE", "0") == "1"
# Blank hale etter innholdet, i piksler (180 dpi, sa 180 px = 25,4 mm).
#
# Skrivehodet sitter omtrent 25 mm inne i maskinen, malt fra utgangsslissen.
# Uten en hale stopper tapen i det siste punktet som er trykt, og da ligger
# slutten av etiketten fortsatt inni printeren: «S4 Morten» er 31 mm, og bare
# 6 mm - en enslig bokstav - kom ut.
#
# Vi printer blanke rader framfor a be om margin. ESC i d ble provd forst og
# mater FOER trykket pa denne modellen, sa 180 der gjorde etiketten helt blank
# i stedet for a redde den. Blanke rader er utvetydige: tapen matte flytte seg
# for a printe dem.
#
# Koster ingen ekstra tape i lengden - halen blir neste etiketts forkant.
# Kommer det for mye blankt etter QR-koden, senk tallet. Blir slutten fortsatt
# borte, ok det.
PRINT_HALE = int(os.environ.get("TP_PRINT_HALE", "190"))
PRINT_TIDSAVBRUDD = int(os.environ.get("TP_PRINT_TIDSAVBRUDD", "30"))
PRINT_MAKS_FORSOK = int(os.environ.get("TP_PRINT_MAKS_FORSOK", "12"))
# Pause etter hver strimmel, sa tapen kommer helt ut for neste jobb starter.
PRINT_HVILE = float(os.environ.get("TP_PRINT_HVILE", "2.0"))

TIDSSONE = ZoneInfo(os.environ.get("TP_TIDSSONE", "Europe/Oslo"))

# E-post er best effort. Uten SMTP-vert logges den og hoppes over.
SMTP_VERT = os.environ.get("TP_SMTP_VERT", "")
SMTP_PORT = int(os.environ.get("TP_SMTP_PORT", "587"))
SMTP_BRUKER = os.environ.get("TP_SMTP_BRUKER", "")
SMTP_PASSORD = os.environ.get("TP_SMTP_PASSORD", "")
EPOST_FRA = os.environ.get("TP_EPOST_FRA", "Tyholt Pizzeria <ikke-svar@afrasum.dev>")
EPOST_MAKS_FORSOK = int(os.environ.get("TP_EPOST_MAKS_FORSOK", "3"))

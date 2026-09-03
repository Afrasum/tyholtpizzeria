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
PRINTLABEL_STI = Path(
    os.environ.get("TP_PRINTLABEL", ROT / "vendor" / "PT-P300BT" / "printlabel.py")
)
PRINT_TIDSAVBRUDD = int(os.environ.get("TP_PRINT_TIDSAVBRUDD", "30"))
PRINT_MAKS_FORSOK = int(os.environ.get("TP_PRINT_MAKS_FORSOK", "3"))

TIDSSONE = ZoneInfo(os.environ.get("TP_TIDSSONE", "Europe/Oslo"))

# E-post er best effort. Uten SMTP-vert logges den og hoppes over.
SMTP_VERT = os.environ.get("TP_SMTP_VERT", "")
SMTP_PORT = int(os.environ.get("TP_SMTP_PORT", "587"))
SMTP_BRUKER = os.environ.get("TP_SMTP_BRUKER", "")
SMTP_PASSORD = os.environ.get("TP_SMTP_PASSORD", "")
EPOST_FRA = os.environ.get("TP_EPOST_FRA", "Tyholt Pizzeria <ikke-svar@afrasum.dev>")
EPOST_MAKS_FORSOK = int(os.environ.get("TP_EPOST_MAKS_FORSOK", "3"))

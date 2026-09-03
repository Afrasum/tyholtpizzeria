"""Nøkkel/verdi-innstillinger som kan endres uten deploy.

Vipps-mottakeren ligger her nettopp fordi den skal kunne rulleres — det var
et uttalt krav. Bytt navn og nummer i admin, og både kvitteringssida og
e-postene følger med umiddelbart.
"""

from __future__ import annotations

import sqlite3

from .db import kobling, naa, transaksjon

STANDARD = {
    "vipps_navn": "",
    "vipps_nummer": "",
    "manuelt_stengt": "0",
    "stedsnavn": "Tyholt Pizzeria",
}


def alle(kob: sqlite3.Connection | None = None) -> dict[str, str]:
    def _les(k: sqlite3.Connection) -> dict[str, str]:
        verdier = dict(STANDARD)
        verdier.update(
            {r["nokkel"]: r["verdi"] for r in k.execute("SELECT nokkel, verdi FROM innstilling")}
        )
        return verdier

    if kob is not None:
        return _les(kob)
    with kobling() as k:
        return _les(k)


def sett(nokkel: str, verdi: str) -> None:
    with transaksjon() as kob:
        kob.execute(
            "INSERT INTO innstilling (nokkel, verdi, oppdatert) VALUES (?, ?, ?)"
            " ON CONFLICT(nokkel) DO UPDATE SET verdi = excluded.verdi,"
            " oppdatert = excluded.oppdatert",
            (nokkel, verdi, naa()),
        )


def sett_mange(par: dict[str, str]) -> None:
    with transaksjon() as kob:
        tid = naa()
        for nokkel, verdi in par.items():
            kob.execute(
                "INSERT INTO innstilling (nokkel, verdi, oppdatert) VALUES (?, ?, ?)"
                " ON CONFLICT(nokkel) DO UPDATE SET verdi = excluded.verdi,"
                " oppdatert = excluded.oppdatert",
                (nokkel, verdi, tid),
            )

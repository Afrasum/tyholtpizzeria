"""Nøkkel/verdi-innstillinger som kan endres uten deploy.

Vipps-mottakeren ligger her nettopp fordi den skal kunne rulleres — det var
et uttalt krav. Bytt navn og nummer i admin, og både kvitteringssida og
e-postene følger med umiddelbart.
"""

from __future__ import annotations

import sqlite3

from .db import kobling, naa, transaksjon

STANDARD = {
    "vipps_mottaker_id": "",
    "manuelt_stengt": "0",
    "stedsnavn": "Tyholt Pizzeria",
}

# Vipps-appen apner en betaling direkte pa denne formen. Prefikset er fast;
# bare telefonnummeret varierer, med landskode og uten mellomrom. Verifisert
# mot seks ekte lenker for den ble tatt i bruk.
VIPPS_LENKE = "https://qr.vipps.no/28/2/01/031/47{nummer}?v=1"


def vipps_url(nummer: str) -> str:
    """Betalingslenke utledet fra telefonnummeret.

    Utledet framfor lagret: et duplisert felt kan komme i utakt med kilden,
    og da sender vi folk til feil person sine penger.
    """
    reint = "".join(t for t in (nummer or "") if t.isdigit())
    reint = reint.removeprefix("47") if len(reint) == 10 else reint
    if len(reint) != 8:
        return ""
    return VIPPS_LENKE.format(nummer=reint)


def mottakere(kob: sqlite3.Connection | None = None) -> list[dict]:
    def _les(k):
        return [
            {
                "id": r["id"],
                "navn": r["navn"],
                "nummer": r["nummer"],
                "url": vipps_url(r["nummer"]),
            }
            for r in k.execute(
                "SELECT * FROM vipps_mottaker ORDER BY rekkefolge, navn"
            )
        ]

    if kob is not None:
        return _les(kob)
    with kobling() as k:
        return _les(k)


def aktiv_mottaker(kob: sqlite3.Connection | None = None) -> dict | None:
    """Den som tar imot betaling akkurat na.

    Faller tilbake pa den forste i lista hvis ingen er valgt, slik at
    kvitteringen aldri viser et tomt Vipps-felt.
    """
    def _les(k):
        liste = mottakere(k)
        if not liste:
            return None
        rad = k.execute(
            "SELECT verdi FROM innstilling WHERE nokkel = 'vipps_mottaker_id'"
        ).fetchone()
        if rad and rad["verdi"]:
            for m in liste:
                if str(m["id"]) == rad["verdi"]:
                    return m
        return liste[0]

    if kob is not None:
        return _les(kob)
    with kobling() as k:
        return _les(k)


def alle(kob: sqlite3.Connection | None = None) -> dict[str, str]:
    def _les(k: sqlite3.Connection) -> dict[str, str]:
        verdier = dict(STANDARD)
        verdier.update(
            {r["nokkel"]: r["verdi"] for r in k.execute("SELECT nokkel, verdi FROM innstilling")}
        )
        # Vipps-feltene utledes fra den aktive mottakeren, slik at maler og
        # e-poster kan lese dem uten a vite om mottakertabellen.
        aktiv = aktiv_mottaker(k)
        verdier["vipps_navn"] = aktiv["navn"] if aktiv else ""
        verdier["vipps_nummer"] = aktiv["nummer"] if aktiv else ""
        verdier["vipps_url"] = aktiv["url"] if aktiv else ""
        return verdier

    if kob is not None:
        return _les(kob)
    with kobling() as k:
        return _les(k)


def legg_til_mottaker(navn: str, nummer: str) -> None:
    with transaksjon() as kob:
        neste = kob.execute(
            "SELECT COALESCE(MAX(rekkefolge), 0) + 1 AS n FROM vipps_mottaker"
        ).fetchone()["n"]
        kob.execute(
            "INSERT INTO vipps_mottaker (navn, nummer, rekkefolge) VALUES (?, ?, ?)"
            " ON CONFLICT(nummer) DO UPDATE SET navn = excluded.navn",
            (navn, nummer, neste),
        )


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

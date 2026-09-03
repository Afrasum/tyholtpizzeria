"""Menyoppslag for kundesida og admin."""

from __future__ import annotations

import sqlite3

from . import allergener
from .db import naa, transaksjon


def full_meny(kob: sqlite3.Connection, bare_tilgjengelige: bool = False) -> list[dict]:
    """Menyen med utledede allergener per rett.

    Allergenene er ikke lagret på retten — de utledes fra ingrediensene hver
    gang. Bytter vi topping, følger allergenlista etter av seg selv.
    """
    sporsmal = "SELECT * FROM menyelement"
    if bare_tilgjengelige:
        sporsmal += " WHERE tilgjengelig = 1"
    sporsmal += " ORDER BY rekkefolge, id"

    ut = []
    for rad in kob.execute(sporsmal):
        ingredienser = [
            r["navn"]
            for r in kob.execute(
                """
                SELECT i.navn FROM menyelement_ingrediens mi
                JOIN ingrediens i ON i.id = mi.ingrediens_id
                WHERE mi.menyelement_id = ? ORDER BY mi.rekkefolge
                """,
                (rad["id"],),
            )
        ]
        ut.append(
            {
                "id": rad["id"],
                "slug": rad["slug"],
                "navn": rad["navn"],
                "beskrivelse": rad["beskrivelse"],
                "pris_ore": rad["pris_ore"],
                "pris_kr": rad["pris_ore"] // 100,
                "tilgjengelig": bool(rad["tilgjengelig"]),
                "ingredienser": ingredienser,
                "inneholder": [
                    dict(r) for r in allergener.for_menyelement(kob, rad["id"])
                ],
            }
        )
    return ut


def sett_tilgjengelig(menyelement_id: int, tilgjengelig: bool) -> None:
    """Utsolgt-bryteren i admin."""
    with transaksjon() as kob:
        kob.execute(
            "UPDATE menyelement SET tilgjengelig = ?, oppdatert = ? WHERE id = ?",
            (1 if tilgjengelig else 0, naa(), menyelement_id),
        )

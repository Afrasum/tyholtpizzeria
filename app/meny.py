"""Menyoppslag for kundesida og admin."""

from __future__ import annotations

import sqlite3

from . import allergener
from .db import naa, transaksjon

# Kallenavn er ren pynt pa kundesida. De ligger her og ikke i basen med vilje:
# navn og etikettnavn styrer kodebokstaven og bytene som gaar til printeren, og
# de skal ikke kunne roeres av en tulletekst. Vil du bytte et kallenavn, bytt
# det her - ingenting annet henger etter.
KALLENAVN: dict[str, str] = {
    "margherita": "Marcus og Margherita",
    "skinke": "Don Skinkone",
    "paere": "Pæreoni & Pérignon",
}


def _undertittel(navn: str, beskrivelse: str) -> str:
    """«Margherita — tomatsaus og revet ost.»

    Det ekte navnet foerst, saa beskrivelsen med liten forbokstav. Naar
    overskriften er et kallenavn, er det denne linja som forteller kunden hva
    de faktisk bestiller.
    """
    if not beskrivelse:
        return navn
    return f"{navn} — {beskrivelse[:1].lower()}{beskrivelse[1:]}"


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
                # Kodebokstaven pa kundesida MA komme herfra, ikke fra navnet:
                # «Hvit pizza med pære» ville gitt H, mens etiketten sier P.
                "etikettnavn": rad["etikettnavn"],
                "kode": rad["etikettnavn"][:1].upper(),
                "beskrivelse": rad["beskrivelse"],
                "kallenavn": KALLENAVN.get(rad["slug"], rad["navn"]),
                "undertittel": _undertittel(rad["navn"], rad["beskrivelse"]),
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

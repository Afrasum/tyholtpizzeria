"""Startdata: allergenvokabular, meny, ingredienser, salgsdager, innstillinger.

Idempotent — trygt å kjøre ved hver oppstart.

VIKTIG OM INGREDIENSENE: radene under er PLASSHOLDERE, markert
verifisert = 0. Allergenene er utledet fra det som er sagt muntlig, ikke lest
av emballasjen. Så lenge admin viser uverifiserte ingredienser er
allergenlista et utkast, ikke en garanti.
"""

from __future__ import annotations

import sqlite3

from . import allergener
from .db import naa, transaksjon

PRIS_ORE = 5900  # 59 kr flat for alle tre.

# (navn, [allergenkoder], notat, verifisert)
# Deigen ligger som egen ingrediens på alle tre pizzaene. Uten den ville alle
# tre blitt utledet som glutenfrie, siden ingrediensene vi fikk oppgitt bare
# var toppingene.
INGREDIENSER: tuple[tuple[str, list[str], str, int], ...] = (
    ("Pizzadeig", ["gluten"], "PLASSHOLDER: antatt hvetemel. Avklar durum/semulegryn.", 0),
    ("Tomatsaus", [], "PLASSHOLDER: sjekk emballasje for sulfitt.", 0),
    ("Revet ost", ["melk"], "PLASSHOLDER: mozzarella eller ferdigrevet blanding?", 0),
    ("Skinke", ["melk"], "PLASSHOLDER: norsk kokt skinke har ofte melkeprotein eller soya som bindemiddel. LES PAKKA.", 0),
    ("Crème fraîche", ["melk"], "PLASSHOLDER: sjekk om varianten har stabilisatorer.", 0),
    ("Pære", [], "Fersk, i tynne skiver.", 0),
)

# (slug, navn, etikettnavn, beskrivelse, ingrediensnavn, rekkefølge)
MENY: tuple[tuple[str, str, str, str, list[str], int], ...] = (
    (
        "margherita",
        "Margherita",
        "Margherita",
        "Tomatsaus og revet ost.",
        ["Pizzadeig", "Tomatsaus", "Revet ost"],
        1,
    ),
    (
        "skinke",
        "Skinke",
        "Skinke",
        "Margherita med skinke.",
        ["Pizzadeig", "Tomatsaus", "Revet ost", "Skinke"],
        2,
    ),
    (
        "paere",
        "Hvit pizza med pære",
        "Pære",
        "Crème fraîche-basert saus med tynne skiver pære.",
        ["Pizzadeig", "Crème fraîche", "Revet ost", "Pære"],
        3,
    ),
)

# Åpent 15:00–00:00, kun 4. og 5. september 2026.
SALGSDAGER: tuple[tuple[str, str, str], ...] = (
    ("2026-09-04", "2026-09-04T15:00:00+02:00", "2026-09-05T00:00:00+02:00"),
    ("2026-09-05", "2026-09-05T15:00:00+02:00", "2026-09-06T00:00:00+02:00"),
)

INNSTILLINGER: dict[str, str] = {
    "vipps_navn": "Afras Mansoor",
    "vipps_nummer": "40166715",
    "manuelt_stengt": "0",
    "stedsnavn": "Tyholt Pizzeria",
}


def _ingrediens(kob: sqlite3.Connection, navn: str, koder: list[str],
                notat: str, verifisert: int) -> int:
    kob.execute(
        """
        INSERT INTO ingrediens (navn, notat, verifisert) VALUES (?, ?, ?)
        ON CONFLICT(navn) DO NOTHING
        """,
        (navn, notat, verifisert),
    )
    rad = kob.execute("SELECT id FROM ingrediens WHERE navn = ?", (navn,)).fetchone()
    ingrediens_id = int(rad["id"])
    for kode in allergener.valider(koder):
        kob.execute(
            "INSERT INTO ingrediens_allergen (ingrediens_id, allergen_kode)"
            " VALUES (?, ?) ON CONFLICT DO NOTHING",
            (ingrediens_id, kode),
        )
    return ingrediens_id


def kjor() -> None:
    with transaksjon() as kob:
        allergener.seed_kategorier(kob)

        ider = {
            navn: _ingrediens(kob, navn, koder, notat, verifisert)
            for navn, koder, notat, verifisert in INGREDIENSER
        }

        tid = naa()
        for slug, navn, etikettnavn, beskrivelse, ingredienser, rekkefolge in MENY:
            kob.execute(
                """
                INSERT INTO menyelement (slug, navn, etikettnavn, beskrivelse,
                                         pris_ore, rekkefolge, tilgjengelig,
                                         opprettet, oppdatert)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(slug) DO UPDATE SET
                    navn = excluded.navn,
                    etikettnavn = excluded.etikettnavn,
                    beskrivelse = excluded.beskrivelse,
                    rekkefolge = excluded.rekkefolge,
                    oppdatert = excluded.oppdatert
                """,
                (slug, navn, etikettnavn, beskrivelse, PRIS_ORE, rekkefolge, tid, tid),
            )
            rad = kob.execute(
                "SELECT id FROM menyelement WHERE slug = ?", (slug,)
            ).fetchone()
            for i, ingrediensnavn in enumerate(ingredienser):
                kob.execute(
                    "INSERT INTO menyelement_ingrediens"
                    " (menyelement_id, ingrediens_id, rekkefolge)"
                    " VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
                    (rad["id"], ider[ingrediensnavn], i),
                )

        for dato, apner, stenger in SALGSDAGER:
            kob.execute(
                """
                INSERT INTO salgsdag (dato, apner, stenger, aktiv)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(dato) DO UPDATE SET
                    apner = excluded.apner, stenger = excluded.stenger
                """,
                (dato, apner, stenger),
            )

        for nokkel, verdi in INNSTILLINGER.items():
            kob.execute(
                "INSERT INTO innstilling (nokkel, verdi, oppdatert) VALUES (?, ?, ?)"
                " ON CONFLICT(nokkel) DO NOTHING",
                (nokkel, verdi, tid),
            )

        # Spor-lista starter som unionen av alt i menyen, men er manuelt
        # vedlikeholdt videre — kjøkkenet kan ha allergener i hus som ikke
        # står i en eneste pizza.
        finnes = kob.execute(
            "SELECT 1 FROM innstilling WHERE nokkel = ?", (allergener.SPOR_NOKKEL,)
        ).fetchone()
        if not finnes:
            allergener.skriv_spor(kob, allergener.union_i_menyen(kob))

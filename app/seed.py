"""Startdata: allergenvokabular, meny, ingredienser, salgsdager, innstillinger.

Idempotent — trygt å kjøre ved hver oppstart.

VIKTIG OM INGREDIENSENE: radene under er PLASSHOLDERE, markert
verifisert = 0. Allergenene er utledet fra det som er sagt muntlig, ikke lest
av emballasjen. Så lenge admin viser uverifiserte ingredienser er
allergenlista et utkast, ikke en garanti.
"""

from __future__ import annotations

import logging
import sqlite3

from . import allergener, ordrer
from .db import naa, transaksjon

logg = logging.getLogger("tyholt.seed")

PRIS_ORE = 5900  # 59 kr flat for alle tre.

# (navn, [allergenkoder], notat, verifisert)
# Deigen ligger som egen ingrediens på alle tre pizzaene. Uten den ville alle
# tre blitt utledet som glutenfrie, siden ingrediensene vi fikk oppgitt bare
# var toppingene.
# verifisert = 0 betyr at ingen har lest allergenene av emballasjen ennå.
# Notatene under beskriver hva varen ER, ut fra det som er oppgitt muntlig —
# det er et godt utgangspunkt, men ikke en avlesning. Admin viser lista som en
# sjekkliste, sortert etter hvor sannsynlig det er at pakka overrasker oss.
INGREDIENSER: tuple[tuple[str, list[str], str, int], ...] = (
    (
        "Pizzadeig",
        ["gluten"],
        "Blanding av to typer hvetemel (pizza/pinsa-deig), vann, gjær, salt. "
        "RISIKO: lav — begge meltyper er hvete uansett.",
        0,
    ),
    (
        "Tomatsaus",
        [],
        "Tomat, salt, pepper, sukker, olivenolje. "
        "RISIKO: lav — sjekk likevel om hermetikken oppgir sulfitt.",
        0,
    ),
    (
        "Revet ost",
        ["melk"],
        "First Price pizzatopping, ferdigrevet. Melk er sikkert. "
        "RISIKO: middels — ferdigrevet ost har ofte potetstivelse, og noen "
        "blandinger inneholder mer enn ost. LES PAKKA.",
        0,
    ),
    (
        "Skinke",
        ["melk"],
        "Vanlig kokt skinke, salattopping. "
        "RISIKO: HØY — norsk kokt skinke har ofte melkeprotein eller soya "
        "som bindemiddel, og det står bare på baksiden. LES PAKKA FØRST.",
        0,
    ),
    (
        "Crème fraîche med krydder",
        ["melk"],
        "Crème fraîche rørt med krydder, brukt som hvit saus. Melk er sikkert. "
        "RISIKO: lav–middels — sjekk krydderblandingen for sennep og selleri.",
        0,
    ),
    ("Pære", [], "Fersk pære i tynne skiver. RISIKO: ingen.", 0),
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
        "Hvit saus av crème fraîche med krydder, og tynne skiver pære.",
        ["Pizzadeig", "Crème fraîche med krydder", "Revet ost", "Pære"],
        3,
    ),
)

# Ett sammenhengende lop, ikke datoer.
#
# Salgsdager var opprinnelig en rad per dato, med en teller som startet forfra
# hver dag. Det kostet mer enn det smakte: en bestilling lagt inn for
# apningstid havnet pa gardagens rad og forsvant fra bade admin og tavla i det
# klokka slo over. Na finnes det noyaktig EN rad, og alt henger pa den.
#
# Kolonnene dato/apner/stenger star igjen i skjemaet fordi de er harmlose og
# fordi a fjerne dem er en migrering uten gevinst. De brukes ikke til noe:
# apningstiden er den manuelle bryteren i admin, og ingenting annet.
LOPET = "lopende"

INNSTILLINGER: dict[str, str] = {
    "manuelt_stengt": "0",
    "stedsnavn": "Tyholt Pizzeria",
}

# Hvem som kan ta imot betaling. Rekkefolgen er den de vises i i admin.
# Betalingslenken lagres ikke - den utledes fra nummeret.
VIPPS_MOTTAKERE: tuple[tuple[str, str], ...] = (
    ("Afras", "40166715"),
    ("Torkil", "93604144"),
    ("Kristian", "90214070"),
    ("Andreas", "95369058"),
    ("Tobias", "90831803"),
    ("Morten", "41783544"),
)


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


def _velg_lopet(kob) -> int:
    """Peke ut den ene salgsdagsraden alt henger pa, og huske valget.

    Rekkefolgen er hele poenget ved oppgradering fra dagsmodellen. Finnes det
    alt ordrer, MA vi velge raden de ligger pa - ellers ville kveldens
    bestillinger blitt usynlige i det denne koden ble tatt i bruk.

      1. raden innstilling['salgsdag_id'] alt peker pa
      2. raden den nyeste ordren ligger pa
      3. den forste raden som finnes
      4. en ny, hvis basen er helt fersk

    Idempotent: kjores ved hver oppstart og velger samme rad hver gang.
    """
    rad = kob.execute(
        "SELECT s.id FROM salgsdag s JOIN innstilling i"
        " ON i.verdi = CAST(s.id AS TEXT) WHERE i.nokkel = 'salgsdag_id'"
    ).fetchone()
    if rad is None:
        rad = kob.execute(
            "SELECT salgsdag_id AS id FROM ordre ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if rad is None:
        rad = kob.execute("SELECT id FROM salgsdag ORDER BY id LIMIT 1").fetchone()
    if rad is None:
        tid = naa()
        markor = kob.execute(
            """
            INSERT INTO salgsdag (dato, apner, stenger, aktiv, startnummer)
            VALUES (?, ?, ?, 1, ?)
            """,
            (LOPET, tid, tid, ordrer.tilfeldig_startnummer()),
        )
        lopet = int(markor.lastrowid)
    else:
        lopet = int(rad["id"])

    kob.execute(
        "INSERT INTO innstilling (nokkel, verdi, oppdatert)"
        " VALUES ('salgsdag_id', ?, ?)"
        " ON CONFLICT(nokkel) DO UPDATE SET verdi = excluded.verdi,"
        " oppdatert = excluded.oppdatert",
        (str(lopet), naa()),
    )
    # Logges fordi valget er det ene som kan ga galt ved oppgradering fra
    # dagsmodellen: peker vi pa feil rad, blir eksisterende ordrer usynlige.
    # Da skal det sta i loggen hvilken rad som ble valgt, ikke gjettes.
    rad = kob.execute(
        "SELECT dato, startnummer, sistenummer FROM salgsdag WHERE id = ?", (lopet,)
    ).fetchone()
    antall = kob.execute(
        "SELECT COUNT(*) AS n FROM ordre WHERE salgsdag_id = ?", (lopet,)
    ).fetchone()["n"]
    logg.info(
        "lopet er salgsdag %s (%s), start %s, sist utdelt %s, %s ordrer",
        lopet, rad["dato"], rad["startnummer"], rad["sistenummer"], antall,
    )
    return lopet


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

        _velg_lopet(kob)

        for i, (navn, nummer) in enumerate(VIPPS_MOTTAKERE):
            kob.execute(
                """
                INSERT INTO vipps_mottaker (navn, nummer, rekkefolge)
                VALUES (?, ?, ?)
                ON CONFLICT(nummer) DO UPDATE SET
                    navn = excluded.navn, rekkefolge = excluded.rekkefolge
                """,
                (navn, nummer, i),
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

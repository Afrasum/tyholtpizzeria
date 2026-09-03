"""De 14 deklarasjonspliktige allergenkategoriene, og utledning av dem.

Kategoriene følger matinformasjonsforskriften, som gjennomfører EU-forordning
1169/2011 vedlegg II i norsk rett. Lista er lukket: en ingrediens kan bare
merkes med koder herfra. Det er hele poenget med et kontrollert vokabular —
fritekst gir «melkeprotein», «laktose» og «melk» som tre ulike ting, og da
finner ikke kunden det de leter etter.

To begreper som ikke må blandes:

  inneholder      — utledet fra ingrediensene i den enkelte pizzaen
  kan inneholde   — én global liste, fordi alt lages på samme kjøkken
  spor av           og vi ikke kan garantere mot krysskontaminering
"""

from __future__ import annotations

import json
import sqlite3

from .db import naa

# (kode, navn, presisering)
KATEGORIER: tuple[tuple[str, str, str], ...] = (
    ("gluten", "Glutenholdig korn", "hvete, rug, bygg, havre, spelt, kamut"),
    ("krepsdyr", "Krepsdyr", ""),
    ("egg", "Egg", ""),
    ("fisk", "Fisk", ""),
    ("peanotter", "Peanøtter", ""),
    ("soya", "Soya", ""),
    ("melk", "Melk", "inkludert laktose"),
    ("notter", "Nøtter", "mandel, hasselnøtt, valnøtt, cashew, pekan, paranøtt, pistasj, macadamia"),
    ("selleri", "Selleri", ""),
    ("sennep", "Sennep", ""),
    ("sesam", "Sesamfrø", ""),
    ("sulfitt", "Svoveldioksid og sulfitt", "over 10 mg/kg"),
    ("lupin", "Lupin", ""),
    ("blotdyr", "Bløtdyr", "skjell, blekksprut, snegler"),
)

KODER: frozenset[str] = frozenset(kode for kode, _, _ in KATEGORIER)

# Nøkkelen den globale spor-lista ligger under i innstilling-tabellen.
SPOR_NOKKEL = "spor_av"


def seed_kategorier(kob: sqlite3.Connection) -> None:
    """Legg inn vokabularet. Idempotent — oppdaterer navn hvis de er endret."""
    for rekkefolge, (kode, navn, presisering) in enumerate(KATEGORIER):
        kob.execute(
            """
            INSERT INTO allergen (kode, navn, presisering, rekkefolge)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(kode) DO UPDATE SET
                navn = excluded.navn,
                presisering = excluded.presisering,
                rekkefolge = excluded.rekkefolge
            """,
            (kode, navn, presisering, rekkefolge),
        )


def valider(koder: list[str]) -> list[str]:
    """Avvis alt som ikke er en av de 14. Kaster framfor å tie stille."""
    ukjente = sorted(set(koder) - KODER)
    if ukjente:
        raise ValueError(
            f"ukjente allergenkoder: {', '.join(ukjente)}. "
            f"Lovlige: {', '.join(sorted(KODER))}"
        )
    return koder


def for_menyelement(kob: sqlite3.Connection, menyelement_id: int) -> list[sqlite3.Row]:
    """Allergener pizzaen *inneholder*, utledet fra ingrediensene.

    Unionen over ingrediensene, sortert i forskriftens rekkefølge. Endrer vi en
    topping oppdateres allergenlista av seg selv — ingen liste å glemme.
    """
    return list(
        kob.execute(
            """
            SELECT DISTINCT a.kode, a.navn, a.presisering
            FROM menyelement_ingrediens mi
            JOIN ingrediens_allergen ia ON ia.ingrediens_id = mi.ingrediens_id
            JOIN allergen a ON a.kode = ia.allergen_kode
            WHERE mi.menyelement_id = ?
            ORDER BY a.rekkefolge
            """,
            (menyelement_id,),
        )
    )


def uverifiserte_ingredienser(kob: sqlite3.Connection) -> list[sqlite3.Row]:
    """Ingredienser der allergenene ikke er lest av på emballasjen ennå.

    Vises i admin. Så lenge denne ikke er tom, er allergenlista et utkast.
    """
    return list(
        kob.execute(
            """
            SELECT i.id, i.navn, i.notat,
                   GROUP_CONCAT(m.navn, ', ') AS brukt_i
            FROM ingrediens i
            LEFT JOIN menyelement_ingrediens mi ON mi.ingrediens_id = i.id
            LEFT JOIN menyelement m ON m.id = mi.menyelement_id
            WHERE i.verifisert = 0
            GROUP BY i.id
            ORDER BY i.navn
            """
        )
    )


def les_spor(kob: sqlite3.Connection) -> list[sqlite3.Row]:
    """Den globale «kan inneholde spor av»-lista, som allergenrader."""
    rad = kob.execute(
        "SELECT verdi FROM innstilling WHERE nokkel = ?", (SPOR_NOKKEL,)
    ).fetchone()
    koder = json.loads(rad["verdi"]) if rad else []
    if not koder:
        return []
    plassholdere = ",".join("?" * len(koder))
    return list(
        kob.execute(
            f"SELECT kode, navn, presisering FROM allergen "
            f"WHERE kode IN ({plassholdere}) ORDER BY rekkefolge",
            koder,
        )
    )


def skriv_spor(kob: sqlite3.Connection, koder: list[str]) -> None:
    """Sett den globale spor-lista. Manuelt vedlikeholdt, ikke utledet.

    Med vilje uavhengig av hva pizzaene inneholder: kjøkkenet kan ha nøtter
    eller sesam i hus uten at det står i en eneste pizza, og da må lista kunne
    si det likevel.
    """
    valider(koder)
    kob.execute(
        """
        INSERT INTO innstilling (nokkel, verdi, oppdatert) VALUES (?, ?, ?)
        ON CONFLICT(nokkel) DO UPDATE SET
            verdi = excluded.verdi, oppdatert = excluded.oppdatert
        """,
        (SPOR_NOKKEL, json.dumps(sorted(set(koder))), naa()),
    )


def union_i_menyen(kob: sqlite3.Connection) -> list[str]:
    """Alle allergener som finnes i minst én pizza.

    Brukes til å foreslå en startverdi for spor-lista i admin — aldri til å
    overskrive den automatisk.
    """
    return [
        r["kode"]
        for r in kob.execute(
            """
            SELECT DISTINCT a.kode
            FROM ingrediens_allergen ia
            JOIN allergen a ON a.kode = ia.allergen_kode
            JOIN menyelement_ingrediens mi ON mi.ingrediens_id = ia.ingrediens_id
            ORDER BY a.rekkefolge
            """
        )
    ]

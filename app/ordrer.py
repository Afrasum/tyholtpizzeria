"""Ordrelogikk: opprettelse, dagsnummer og statusflyt.

Dette er systemets kjerne. Alt annet — meny, etiketter, e-post, skjerm —
henger på at det som skjer her er riktig.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from . import config
from .db import naa, transaksjon

# Produksjonsløpet. Betaling er IKKE en status: den skjer på Vipps utenfor
# systemet og bekreftes ved henting, så den lever i ordre.betalt.
FLYT: dict[str, tuple[str, ...]] = {
    "ny": ("i_produksjon", "klar", "avbrutt"),
    "i_produksjon": ("klar", "avbrutt"),
    "klar": ("levert", "i_produksjon", "avbrutt"),
    "levert": (),
    "avbrutt": ("ny",),
}

STATUSNAVN: dict[str, str] = {
    "ny": "Ny",
    "i_produksjon": "I produksjon",
    "klar": "Klar til henting",
    "levert": "Levert",
    "avbrutt": "Avbrutt",
}


class Avvist(Exception):
    """Bestillingen kan ikke gjennomføres. Meldingen vises til kunden."""


@dataclass(frozen=True)
class Onske:
    """En linje i handlekorgen, slik den kommer fra kunden."""

    menyelement_id: int
    antall: int


# ── Salgsdag ────────────────────────────────────────────────────────────────


def aapen_salgsdag(kob: sqlite3.Connection, tid: datetime | None = None) -> sqlite3.Row | None:
    """Salgsdagen vi er inne i nå, eller None hvis det er stengt.

    Sammenligner ISO-8601-strenger med tidssone direkte. Det er trygt her
    fordi alle rader skrives i samme sone med samme format, så leksikografisk
    rekkefølge er kronologisk rekkefølge.
    """
    nu = (tid or datetime.now(config.TIDSSONE)).isoformat(timespec="seconds")
    return kob.execute(
        """
        SELECT * FROM salgsdag
        WHERE aktiv = 1 AND apner <= ? AND stenger >= ?
        ORDER BY apner LIMIT 1
        """,
        (nu, nu),
    ).fetchone()


def _manuelt_stengt(kob: sqlite3.Connection) -> bool:
    rad = kob.execute(
        "SELECT verdi FROM innstilling WHERE nokkel = 'manuelt_stengt'"
    ).fetchone()
    return bool(rad and rad["verdi"] == "1")


def kan_bestille(kob: sqlite3.Connection) -> tuple[bool, str]:
    """(åpent, begrunnelse). Begrunnelsen vises til kunden når det er stengt."""
    if _manuelt_stengt(kob):
        return False, "Vi har midlertidig stengt for bestilling."
    if aapen_salgsdag(kob) is None:
        return False, "Vi har stengt akkurat nå."
    return True, ""


# ── Opprettelse ─────────────────────────────────────────────────────────────


def _neste_dagsnummer(kob: sqlite3.Connection, salgsdag_id: int) -> int:
    """Neste ledige nummer for salgsdagen.

    Trygg fordi kalleren holder BEGIN IMMEDIATE-låsen: to samtidige
    bestillinger kan ikke lese samme MAX. UNIQUE(salgsdag_id, dagsnummer) i
    schemaet er beltet i tillegg til bukseselene.
    """
    rad = kob.execute(
        "SELECT COALESCE(MAX(dagsnummer), 0) + 1 AS neste FROM ordre WHERE salgsdag_id = ?",
        (salgsdag_id,),
    ).fetchone()
    return int(rad["neste"])


def opprett(
    kundenavn: str,
    epost: str | None,
    onsker: list[Onske],
    notat: str = "",
) -> dict:
    """Opprett en ordre med linjer og etikettjobber, i én transaksjon.

    Returnerer nok informasjon til kvitteringssiden. Kaster `Avvist` med en
    kundevennlig melding hvis noe ikke går.

    Alt skjer under én lås: nummertildeling, linjer og printjobber. Enten får
    kunden et nummer og kjøkkenet etiketter, eller ingenting skjer. Vi skal
    aldri ende med en ordre uten etikett, eller en etikett uten ordre.
    """
    kundenavn = " ".join(kundenavn.split())
    if not kundenavn:
        raise Avvist("Vi trenger et navn for å rope deg opp.")
    if len(kundenavn) > 60:
        raise Avvist("Navnet er for langt.")

    epost = (epost or "").strip() or None
    if epost and ("@" not in epost or len(epost) > 200):
        raise Avvist("E-postadressen ser ikke riktig ut.")

    onsker = [o for o in onsker if o.antall > 0]
    if not onsker:
        raise Avvist("Handlekorgen er tom.")

    antall_pizzaer = sum(o.antall for o in onsker)
    if antall_pizzaer > 20:
        raise Avvist(
            "Mer enn 20 pizzaer i én bestilling — ta kontakt med oss direkte."
        )

    with transaksjon() as kob:
        aapent, grunn = kan_bestille(kob)
        if not aapent:
            raise Avvist(grunn)

        dag = aapen_salgsdag(kob)
        assert dag is not None  # kan_bestille har alt slått fast dette

        # Les menyen inne i transaksjonen. Blir en pizza utsolgt i samme
        # øyeblikk, skal denne bestillingen se det.
        valgte: list[tuple[sqlite3.Row, int]] = []
        for onske in onsker:
            rad = kob.execute(
                "SELECT * FROM menyelement WHERE id = ?", (onske.menyelement_id,)
            ).fetchone()
            if rad is None:
                raise Avvist("En av rettene finnes ikke lenger.")
            if not rad["tilgjengelig"]:
                raise Avvist(f"{rad['navn']} er dessverre utsolgt.")
            valgte.append((rad, onske.antall))

        total_ore = sum(rad["pris_ore"] * antall for rad, antall in valgte)
        nummer = _neste_dagsnummer(kob, dag["id"])
        tid = naa()

        markor = kob.execute(
            """
            INSERT INTO ordre (salgsdag_id, dagsnummer, kundenavn, epost,
                               status, betalt, total_ore, notat,
                               opprettet, oppdatert)
            VALUES (?, ?, ?, ?, 'ny', 0, ?, ?, ?, ?)
            """,
            (dag["id"], nummer, kundenavn, epost, total_ore, notat.strip(), tid, tid),
        )
        ordre_id = int(markor.lastrowid)

        kob.execute(
            "INSERT INTO statuslogg (ordre_id, fra_status, til_status, aktor, opprettet)"
            " VALUES (?, NULL, 'ny', 'kunde', ?)",
            (ordre_id, tid),
        )

        # Én etikett per pizza per antall, med teller. To like etiketter på en
        # 2x-ordre gir kokken ingen måte å telle esker på, og servitøren ingen
        # måte å se at én mangler.
        etiketter: list[dict] = []
        for rad, antall in valgte:
            kob.execute(
                """
                INSERT INTO ordrelinje (ordre_id, menyelement_id, navn_snapshot,
                                        etikett_snapshot, pris_ore_snapshot, antall)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (ordre_id, rad["id"], rad["navn"], rad["etikettnavn"],
                 rad["pris_ore"], antall),
            )
            for _ in range(antall):
                etiketter.append({"tekst": rad["etikettnavn"]})

        for indeks, etikett in enumerate(etiketter, start=1):
            nyttelast = {
                "ordre_id": ordre_id,
                "nummer": nummer,
                "kundenavn": kundenavn,
                "tekst": etikett["tekst"],
                "indeks": indeks,
                "av": len(etiketter),
            }
            kob.execute(
                """
                INSERT INTO jobb (type, nyttelast, status, ordre_id, opprettet, oppdatert)
                VALUES ('etikett', ?, 'ny', ?, ?, ?)
                """,
                (json.dumps(nyttelast, ensure_ascii=False), ordre_id, tid, tid),
            )

        if epost:
            kob.execute(
                """
                INSERT INTO jobb (type, nyttelast, status, ordre_id, opprettet, oppdatert)
                VALUES ('epost', ?, 'ny', ?, ?, ?)
                """,
                (
                    json.dumps(
                        {"ordre_id": ordre_id, "mal": "bestilling_mottatt"},
                        ensure_ascii=False,
                    ),
                    ordre_id,
                    tid,
                    tid,
                ),
            )

        return {
            "ordre_id": ordre_id,
            "nummer": nummer,
            "kundenavn": kundenavn,
            "total_ore": total_ore,
            "antall_etiketter": len(etiketter),
        }


# ── Statusflyt ──────────────────────────────────────────────────────────────


def sett_status(ordre_id: int, ny_status: str, aktor: str = "admin") -> sqlite3.Row:
    """Flytt en ordre. Avviser ulovlige overganger framfor å tie stille.

    Sender e-post når ordren blir klar til henting.
    """
    if ny_status not in FLYT:
        raise Avvist(f"Ukjent status: {ny_status}")

    with transaksjon() as kob:
        ordre = kob.execute("SELECT * FROM ordre WHERE id = ?", (ordre_id,)).fetchone()
        if ordre is None:
            raise Avvist("Ordren finnes ikke.")

        fra = ordre["status"]
        if fra == ny_status:
            return ordre
        if ny_status not in FLYT[fra]:
            raise Avvist(
                f"Kan ikke gå fra {STATUSNAVN[fra]} til {STATUSNAVN[ny_status]}."
            )

        tid = naa()
        kob.execute(
            "UPDATE ordre SET status = ?, oppdatert = ? WHERE id = ?",
            (ny_status, tid, ordre_id),
        )
        kob.execute(
            "INSERT INTO statuslogg (ordre_id, fra_status, til_status, aktor, opprettet)"
            " VALUES (?, ?, ?, ?, ?)",
            (ordre_id, fra, ny_status, aktor, tid),
        )

        if ny_status == "klar" and ordre["epost"]:
            kob.execute(
                """
                INSERT INTO jobb (type, nyttelast, status, ordre_id, opprettet, oppdatert)
                VALUES ('epost', ?, 'ny', ?, ?, ?)
                """,
                (
                    json.dumps(
                        {"ordre_id": ordre_id, "mal": "klar_til_henting"},
                        ensure_ascii=False,
                    ),
                    ordre_id,
                    tid,
                    tid,
                ),
            )

        return kob.execute("SELECT * FROM ordre WHERE id = ?", (ordre_id,)).fetchone()


def sett_betalt(ordre_id: int, betalt: bool, aktor: str = "admin") -> None:
    """Marker betaling bekreftet. Ortogonal til produksjonsstatus."""
    with transaksjon() as kob:
        tid = naa()
        kob.execute(
            "UPDATE ordre SET betalt = ?, oppdatert = ? WHERE id = ?",
            (1 if betalt else 0, tid, ordre_id),
        )
        kob.execute(
            "INSERT INTO statuslogg (ordre_id, fra_status, til_status, aktor, opprettet)"
            " VALUES (?, NULL, ?, ?, ?)",
            (ordre_id, "betalt" if betalt else "ikke_betalt", aktor, tid),
        )


# ── Oppslag ─────────────────────────────────────────────────────────────────


def med_linjer(kob: sqlite3.Connection, ordre_id: int) -> dict | None:
    ordre = kob.execute("SELECT * FROM ordre WHERE id = ?", (ordre_id,)).fetchone()
    if ordre is None:
        return None
    linjer = list(
        kob.execute(
            "SELECT * FROM ordrelinje WHERE ordre_id = ? ORDER BY id", (ordre_id,)
        )
    )
    return {"ordre": ordre, "linjer": linjer}


def for_admin(kob: sqlite3.Connection, salgsdag_id: int | None = None) -> list[dict]:
    """Alle ordrer for admin-tabellen, nyeste først, med linjer og printstatus."""
    if salgsdag_id is None:
        dag = aapen_salgsdag(kob)
        if dag is None:
            rad = kob.execute(
                "SELECT id FROM salgsdag ORDER BY apner DESC LIMIT 1"
            ).fetchone()
            salgsdag_id = rad["id"] if rad else None
        else:
            salgsdag_id = dag["id"]
    if salgsdag_id is None:
        return []

    ordrer = list(
        kob.execute(
            "SELECT * FROM ordre WHERE salgsdag_id = ? ORDER BY dagsnummer DESC",
            (salgsdag_id,),
        )
    )
    ut: list[dict] = []
    for ordre in ordrer:
        linjer = list(
            kob.execute(
                "SELECT * FROM ordrelinje WHERE ordre_id = ? ORDER BY id",
                (ordre["id"],),
            )
        )
        print_status = kob.execute(
            """
            SELECT
                SUM(status = 'ferdig') AS ferdig,
                SUM(status = 'feilet') AS feilet,
                COUNT(*)               AS totalt
            FROM jobb WHERE ordre_id = ? AND type = 'etikett'
            """,
            (ordre["id"],),
        ).fetchone()
        ut.append({"ordre": ordre, "linjer": linjer, "print": print_status})
    return ut


def klare_numre(kob: sqlite3.Connection) -> list[int]:
    """Numre som venter på å hentes. Til henteskjermen — kun tall, ingen navn."""
    dag = aapen_salgsdag(kob)
    if dag is None:
        return []
    return [
        r["dagsnummer"]
        for r in kob.execute(
            "SELECT dagsnummer FROM ordre WHERE salgsdag_id = ? AND status = 'klar'"
            " ORDER BY oppdatert",
            (dag["id"],),
        )
    ]

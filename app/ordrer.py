"""Ordrelogikk: opprettelse, dagsnummer og statusflyt.

Dette er systemets kjerne. Alt annet — meny, etiketter, e-post, skjerm —
henger på at det som skjer her er riktig.
"""

from __future__ import annotations

import json
import random
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from . import config
from .db import naa, transaksjon

# Produksjonsløpet. Betaling er IKKE en status: den skjer på Vipps utenfor
# systemet og bekreftes ved henting, så den lever i ordre.betalt.
# «forlatt» er med som en tilstand admin kan sette selv, men ingenting flytter
# en ordre dit automatisk. En automatisk overgang etter 5 minutter ville tatt
# nummeret av henteskjermen mens kunden er på vei bort til kassen — se
# GAMMEL_ETTER_MIN, som bare farger raden i admin.
# Forste oppforing er den forventede veien videre — den blir den rode knappen
# i admin. Resten er sidespor OG angrevei: hver tilstand kan naa gaa tilbake
# dit den kom fra. Et feiltrykk klokka 23 skal koste ett nytt trykk, ikke en
# tur i basen.
FLYT: dict[str, tuple[str, ...]] = {
    "ny": ("i_produksjon", "klar", "avbrutt"),
    "i_produksjon": ("klar", "ny", "avbrutt"),
    "klar": ("levert", "forlatt", "i_produksjon", "avbrutt"),
    "levert": ("klar",),
    "forlatt": ("klar", "levert"),
    "avbrutt": ("ny",),
}

# Kjokkenets ord. Disse staar i admin, der «ny» betyr «ingen har tatt i den».
STATUSNAVN: dict[str, str] = {
    "ny": "Ny",
    "i_produksjon": "I produksjon",
    "klar": "Klar til henting",
    "levert": "Levert",
    "forlatt": "Forlatt",
    "avbrutt": "Avbrutt",
}

# Kundens ord. Samme tilstander, men fortalt slik de oppleves fra andre siden
# av disken: hva har skjedd med MIN pizza. «Ny» sier ingenting til noen som
# nettopp har betalt.
KUNDESTATUS: dict[str, str] = {
    "ny": "Bestilt",
    "i_produksjon": "I ovnen",
    "klar": "Klar til henting",
    "levert": "Hentet",
    "forlatt": "Ikke hentet",
    "avbrutt": "Avbrutt",
}


MAKS_PER_BESTILLING = 10

# Etter så mange minutter som «klar» markeres ordren som gammel i admin.
# Den blir IKKE flyttet automatisk — se merknaden i FLYT.
GAMMEL_ETTER_MIN = 5


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


def tilfeldig_startnummer() -> int:
    """Et tosifret starttall. Ser bedre ut enn å rope opp «nummer 1»."""
    return random.randint(11, 47)


def gjeldende_salgsdag(
    kob: sqlite3.Connection, tid: datetime | None = None
) -> sqlite3.Row | None:
    """Den åpne salgsdagen, ellers den siste som har BEGYNT.

    «Som har begynt» er hele poenget. Naiv nyeste-dag-først gir salgsdag 2 så
    snart den er seedet, og da skjer to ting: under rigging klokka 14:00 den
    4. viser admin en tom tabell, og klokka 00:00:01 den 5. forsvinner hver
    ordre som fortsatt er klar eller i produksjon — fra admin OG fra
    henteskjermen. Vi stenger ved midnatt, så det er nøyaktig da det er
    garantert at det står upplukkede pizzaer i hylla.
    """
    aapen = aapen_salgsdag(kob, tid)
    if aapen is not None:
        return aapen
    nu = (tid or datetime.now(config.TIDSSONE)).isoformat(timespec="seconds")
    return kob.execute(
        "SELECT * FROM salgsdag WHERE apner <= ? ORDER BY apner DESC LIMIT 1",
        (nu,),
    ).fetchone()


def _manuelt_stengt(kob: sqlite3.Connection) -> bool:
    rad = kob.execute(
        "SELECT verdi FROM innstilling WHERE nokkel = 'manuelt_stengt'"
    ).fetchone()
    return bool(rad and rad["verdi"] == "1")


def kan_bestille(kob: sqlite3.Connection) -> tuple[bool, str]:
    """(åpent, begrunnelse). Begrunnelsen vises til kunden når det er stengt.

    ÉN sperre, og bare én: den manuelle bryteren i admin. Klokka er med vilje
    IKKE med her.

    Grunnen er drift. Var åpningstiden en kodet sperre, kunne vi ikke testet
    dagen før, og et kvarter på overtid krevde SQL for å redde. Nå er
    åpningstiden noe menneskene passer på, og systemet gjør som det blir
    fortalt. Salgsdagene finnes fortsatt, men bare til nummerering.
    """
    if _manuelt_stengt(kob):
        return False, "Vi har midlertidig stengt for bestilling."
    return True, ""


def salgsdag_for_ordre(kob: sqlite3.Connection, tid: datetime | None = None) -> sqlite3.Row:
    """Salgsdagen en ny ordre skal nummereres under.

    Rekkefølgen: åpen dag, ellers siste dag som har begynt, ellers lages en
    dag for datoen i dag. Siste ledd gjør at testbestillinger dagen før havner
    på sin egen teller og ikke spiser numre fra kvelden det gjelder.
    """
    dag = gjeldende_salgsdag(kob, tid)
    if dag is not None:
        return dag

    nu = tid or datetime.now(config.TIDSSONE)
    dato = nu.date().isoformat()
    kob.execute(
        """
        INSERT INTO salgsdag (dato, apner, stenger, aktiv, startnummer)
        VALUES (?, ?, ?, 1, ?)
        ON CONFLICT(dato) DO NOTHING
        """,
        (
            dato,
            nu.replace(hour=0, minute=0, second=0).isoformat(timespec="seconds"),
            nu.replace(hour=23, minute=59, second=59).isoformat(timespec="seconds"),
            tilfeldig_startnummer(),
        ),
    )
    return kob.execute("SELECT * FROM salgsdag WHERE dato = ?", (dato,)).fetchone()


# ── Opprettelse ─────────────────────────────────────────────────────────────


MAKS_DAGSNUMMER = 999  # tre siffer er det som får plass stort på etiketten


def _neste_dagsnummer(kob: sqlite3.Connection, salgsdag_id: int) -> int:
    """Neste ledige nummer for salgsdagen.

    Starter på salgsdagens startnummer framfor 1 — et tosifret starttall ser
    ut som vi har holdt på en stund, og koster ingenting.

    Telleren gaar bare oppover. sistenummer husker hoyeste utdelte nummer selv
    etter at ordren er slettet — ellers ville en sletting frigjort nummeret til
    neste kunde, og to esker samme kveld kunne baere samme tall.

    Trygg fordi kalleren holder BEGIN IMMEDIATE-låsen: to samtidige
    bestillinger kan ikke lese samme MAX. UNIQUE(salgsdag_id, dagsnummer) i
    schemaet er beltet i tillegg til bukseselene.
    """
    rad = kob.execute(
        """
        SELECT s.startnummer AS start,
               s.sistenummer AS sist,
               COALESCE(MAX(o.dagsnummer), 0) AS hoyeste
        FROM salgsdag s LEFT JOIN ordre o ON o.salgsdag_id = s.id
        WHERE s.id = ?
        """,
        (salgsdag_id,),
    ).fetchone()

    def _merk(nummer: int) -> int:
        """Skriv nummeret som utdelt for vi gir det fra oss."""
        kob.execute(
            "UPDATE salgsdag SET sistenummer = MAX(sistenummer, ?) WHERE id = ?",
            (nummer, salgsdag_id),
        )
        return nummer

    neste = max(int(rad["hoyeste"]) + 1, int(rad["sist"]) + 1, int(rad["start"]))
    if neste <= MAKS_DAGSNUMMER:
        return _merk(neste)

    # Over 999: fire siffer blir for smått på 12 mm tape, så vi begynner
    # forfra på det laveste ledige. Vi kommer aldri hit på en kveld, men et
    # nummer som ikke får plass på etiketten er verre enn ett som gjentas.
    brukte = {
        r["dagsnummer"]
        for r in kob.execute(
            "SELECT dagsnummer FROM ordre WHERE salgsdag_id = ?", (salgsdag_id,)
        )
    }
    for kandidat in range(1, MAKS_DAGSNUMMER + 1):
        if kandidat not in brukte:
            return _merk(kandidat)
    raise Avvist("Alle numre er brukt opp for i dag. Nullstill dagen i admin.")


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
    if antall_pizzaer > MAKS_PER_BESTILLING:
        raise Avvist(
            f"Maks {MAKS_PER_BESTILLING} pizzaer per bestilling. "
            "Skal du ha flere, snakk med oss i kassen."
        )

    with transaksjon() as kob:
        aapent, grunn = kan_bestille(kob)
        if not aapent:
            raise Avvist(grunn)

        dag = salgsdag_for_ordre(kob)

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
            etikett["indeks"] = indeks
            etikett["av"] = len(etiketter)

        # ÉN jobb for hele ordren, ikke én per pizza. Etikettene printes som en
        # sammenhengende strimmel med klippeguider, slik at vi betaler
        # printerens 2,5 cm forspill én gang framfor én gang per pizza. Det
        # sparer 5 cm på en tre-pizza ordre og koster ingen ekstra klipp.
        kob.execute(
            """
            INSERT INTO jobb (type, nyttelast, status, ordre_id, opprettet, oppdatert)
            VALUES ('etikett', ?, 'ny', ?, ?, ?)
            """,
            (
                json.dumps(
                    {
                        "ordre_id": ordre_id,
                        "nummer": nummer,
                        "kundenavn": kundenavn,
                        "etiketter": etiketter,
                    },
                    ensure_ascii=False,
                ),
                ordre_id,
                tid,
                tid,
            ),
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


def skjul_ordre(ordre_id: int, skjult: bool = True) -> bool:
    """Ta en ordre ut av arbeidsflaten uten a slette den.

    Til feilbestillinger og provetrykk: en ordre som aldri skulle eksistert
    skal forsvinne fra kjokkenkoen og fra tavla, ikke ligge igjen som
    «avbrutt» og stjele oppmerksomhet. Men raden blir staaende i basen, sa
    tallene stemmer naar kvelden gjores opp — og et feiltrykk kan angres.

    Nummeret gjenbrukes IKKE. Telleren teller videre uansett, sa to esker
    aldri kan baere samme tall samme kveld.
    """
    with transaksjon() as kob:
        tid = naa()
        endret = kob.execute(
            "UPDATE ordre SET skjult = ?, oppdatert = ? WHERE id = ?",
            (1 if skjult else 0, tid, ordre_id),
        ).rowcount > 0
        if endret and skjult:
            # Ellers spytter printeren ut etiketten til en ordre som nettopp
            # ble fjernet. Jobber som alt kjorer rekker vi ikke — tapen er i
            # bevegelse — men koen skal toemmes. Jobbtabellen har ingen
            # 'avbrutt'-status, sa vi bruker 'feilet' med grunnen skrevet inn.
            kob.execute(
                "UPDATE jobb SET status = 'feilet', siste_feil = 'ordren ble fjernet',"
                " oppdatert = ? WHERE ordre_id = ? AND status = 'ny'",
                (tid, ordre_id),
            )
        if endret:
            kob.execute(
                "INSERT INTO statuslogg (ordre_id, fra_status, til_status, aktor,"
                " opprettet) VALUES (?, NULL, ?, 'admin', ?)",
                (ordre_id, "skjult" if skjult else "synlig", tid),
            )
        return endret


def slett_ordre(ordre_id: int) -> bool:
    """Slett en ordre for godt. Ingen vei tilbake utenom backupen.

    Skiller seg fra skjul_ordre ved at raden faktisk forsvinner: linjer,
    statuslogg og jobber folger med via ON DELETE CASCADE. Til bestillinger som
    aldri skulle eksistert - provetrykk, dobbeltregistreringer - der det er
    feil at de teller med naar kvelden gjores opp.

    sistenummer roeres IKKE. Nummeret til en slettet ordre skal aldri deles ut
    pa nytt samme kveld, ellers kan to esker baere samme tall.
    """
    with transaksjon() as kob:
        return kob.execute(
            "DELETE FROM ordre WHERE id = ?", (ordre_id,)
        ).rowcount > 0


def slett_dagens_ordrer(salgsdag_id: int) -> int:
    """Slett alle ordrer for en salgsdag. Returnerer antall slettede.

    Finnes for å rydde etter lasttesting og prøvebestillinger. Linjer,
    statuslogg og jobber følger med via ON DELETE CASCADE.

    Destruktivt med vilje uten angremulighet — men backup-timeren tar en kopi
    hvert minutt, så veien tilbake er å pakke ut siste fil fra
    ~/data/tyholtpizzeria/backup/.
    """
    with transaksjon() as kob:
        antall = kob.execute(
            "SELECT COUNT(*) AS n FROM ordre WHERE salgsdag_id = ?", (salgsdag_id,)
        ).fetchone()["n"]
        kob.execute("DELETE FROM ordre WHERE salgsdag_id = ?", (salgsdag_id,))
        # Nullstilling betyr hele dagen om igjen, telleren inkludert — dette
        # er knappen man bruker FOR service, ikke under. Aa slette EN ordre
        # (slett_ordre) rorer bevisst ikke telleren.
        kob.execute(
            "UPDATE salgsdag SET sistenummer = 0 WHERE id = ?", (salgsdag_id,)
        )
        return int(antall)


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


def for_admin(
    kob: sqlite3.Connection,
    salgsdag_id: int | None = None,
    tid: datetime | None = None,
) -> list[dict]:
    """Alle synlige ordrer for admin, ELDSTE forst, med linjer og printstatus.

    Rekkefolgen er ikke smak. Med nyeste oeverst skjot hver nye bestilling alle
    radene ett hakk ned, og et trykk som var pa vei mot «Klar til henting» pa
    nummer 48 landet pa nummer 49. Nederst legger de seg uten a flytte noe.
    """
    if salgsdag_id is None:
        dag = gjeldende_salgsdag(kob, tid)
        salgsdag_id = dag["id"] if dag else None
    if salgsdag_id is None:
        return []

    ordrer = list(
        kob.execute(
            "SELECT * FROM ordre WHERE salgsdag_id = ? AND skjult = 0"
            " ORDER BY dagsnummer ASC",
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


def skjulte_for_admin(
    kob: sqlite3.Connection,
    salgsdag_id: int | None = None,
    tid: datetime | None = None,
) -> list[dict]:
    """De skjulte ordrene, til angrelista i admin.

    Finnes fordi kryss-knappen er ETT trykk uten bekreftelse. Det er den bare
    trygt aa gjoere naar veien tilbake staar rett under lista.
    """
    if salgsdag_id is None:
        dag = gjeldende_salgsdag(kob, tid)
        salgsdag_id = dag["id"] if dag else None
    if salgsdag_id is None:
        return []
    return [
        {"ordre": o}
        for o in kob.execute(
            "SELECT * FROM ordre WHERE salgsdag_id = ? AND skjult = 1"
            " ORDER BY dagsnummer ASC",
            (salgsdag_id,),
        )
    ]


def solgte_pizzaer(
    kob: sqlite3.Connection,
    salgsdag_id: int | None = None,
    tid: datetime | None = None,
) -> int:
    """Antall pizzaer solgt i dag — skjulte ordrer TELLER MED.

    Summeres ikke over admin-tabellen, for den utelater de skjulte. Gjorde vi
    det, ville tellinga gatt nedover mot null etter hvert som leverte ordrer
    ble ryddet vekk i lopet av kvelden.
    """
    if salgsdag_id is None:
        dag = gjeldende_salgsdag(kob, tid)
        salgsdag_id = dag["id"] if dag else None
    if salgsdag_id is None:
        return 0
    rad = kob.execute(
        """
        SELECT COALESCE(SUM(l.antall), 0) AS n
        FROM ordrelinje l JOIN ordre o ON o.id = l.ordre_id
        WHERE o.salgsdag_id = ? AND o.status != 'avbrutt'
        """,
        (salgsdag_id,),
    ).fetchone()
    return int(rad["n"])


def klare_numre(
    kob: sqlite3.Connection, tid: datetime | None = None
) -> list[int]:
    """Numre som venter på å hentes. Til henteskjermen — kun tall, ingen navn.

    Bruker gjeldende_salgsdag, ikke aapen_salgsdag: stenger vi midt i at noen
    venter, skal nummeret deres bli stående til noen faktisk trykker levert.
    """
    dag = gjeldende_salgsdag(kob, tid)
    if dag is None:
        return []
    return [
        r["dagsnummer"]
        for r in kob.execute(
            "SELECT dagsnummer FROM ordre WHERE salgsdag_id = ? AND status = 'klar'"
            " AND skjult = 0 ORDER BY oppdatert",
            (dag["id"],),
        )
    ]

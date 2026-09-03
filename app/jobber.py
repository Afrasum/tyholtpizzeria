"""Jobbkø for etikettprint og e-post.

Én tabell, to arbeidertråder. Tråder framfor asyncio-oppgaver fordi begge
jobbtypene gjør blokkerende kall — subprocess mot printeren, SMTP mot
e-postserveren — og de skal ikke kunne stoppe hendelsesløkken.

Hver type har sin egen arbeider med vilje: en printer som sover og bruker
opp tidsavbruddet sitt tre ganger skal ikke holde igjen kvitteringene.
"""

from __future__ import annotations

import json
import logging
import threading
import time

from . import config, epost, printer
from .db import kobling, naa, transaksjon

logg = logging.getLogger("tyholt.jobber")

HVILE_SEK = 1.0       # hvor ofte en tom kø sjekkes på nytt
MAKS_PAUSE = 60.0     # tak på tilbaketrekningen etter gjentatte feil

MAKS_FORSOK = {
    "etikett": config.PRINT_MAKS_FORSOK,
    "epost": config.EPOST_MAKS_FORSOK,
}


def _krev(jobbtype: str):
    """Ta neste ledige jobb av køen, atomisk.

    UPDATE ... RETURNING gjør krav og lesing til én operasjon, så to
    arbeidere aldri kan ta samme jobb. Vi kjører bare én arbeider per type,
    men det skal være riktig uansett — en gjenopptatt arbeider etter restart
    skal ikke kunne dublere en print.
    """
    with transaksjon() as kob:
        rad = kob.execute(
            """
            UPDATE jobb SET status = 'kjorer', oppdatert = ?
            WHERE id = (
                SELECT id FROM jobb
                WHERE type = ? AND status = 'ny'
                ORDER BY id LIMIT 1
            )
            RETURNING id, type, nyttelast, forsok
            """,
            (naa(), jobbtype),
        ).fetchone()
        return rad


def _fullfor(jobb_id: int) -> None:
    with transaksjon() as kob:
        kob.execute(
            "UPDATE jobb SET status = 'ferdig', siste_feil = '', oppdatert = ? WHERE id = ?",
            (naa(), jobb_id),
        )


def _feil(
    jobb_id: int,
    jobbtype: str,
    forsok: int,
    melding: str,
    vent_i_ro: bool = False,
) -> None:
    """Legg jobben tilbake i køen, eller gi opp hvis den har prøvd nok.

    `vent_i_ro` teller IKKE forsøket. Den brukes når feilen krever et
    menneske — printeren har låst seg og må få strøm av og på. Da skal jobben
    ligge og vente i det uendelige framfor å dø mens noen er på vei bort til
    printeren, slik at køen skriver seg ut av seg selv når den er tilbake.

    Feilede jobber blir liggende med feilmeldingen synlig. Admin har en
    reprint-knapp; ingenting forsvinner i stillhet.
    """
    nytt = forsok if vent_i_ro else forsok + 1
    gir_opp = (not vent_i_ro) and nytt >= MAKS_FORSOK.get(jobbtype, 3)
    with transaksjon() as kob:
        kob.execute(
            "UPDATE jobb SET status = ?, forsok = ?, siste_feil = ?, oppdatert = ?"
            " WHERE id = ?",
            ("feilet" if gir_opp else "ny", nytt, melding[:500], naa(), jobb_id),
        )
    if gir_opp:
        logg.error("jobb %s (%s) ga opp etter %s forsøk: %s", jobb_id, jobbtype, nytt, melding)
    else:
        logg.warning("jobb %s (%s) forsøk %s feilet: %s", jobb_id, jobbtype, nytt, melding)


def handter_feil(rad, jobbtype: str, e: BaseException) -> None:
    """Avgjør hva en feilet jobb skal gjøre videre.

    Bor utenfor arbeiderløkka fordi det er en beslutning, ikke en detalj i
    en løkke — og fordi testene skal kunne kjøre nøyaktig denne logikken
    framfor en kopi som kan komme i utakt.

    Skillet: PrinterLaast krever et menneske (strøm av og på), så forsøket
    telles ikke og jobben venter i det uendelige. Alt annet er en ekte feil
    som skal gi opp etter et antall forsøk.
    """
    krever_menneske = isinstance(e, printer.PrinterLaast)
    _feil(
        rad["id"],
        jobbtype,
        rad["forsok"],
        f"{type(e).__name__}: {e}",
        vent_i_ro=krever_menneske,
    )


def _utfor_etikett(nyttelast: dict) -> None:
    printer.skriv_ut(
        nummer=nyttelast["nummer"],
        etiketter=nyttelast["etiketter"],
        kundenavn=nyttelast.get("kundenavn", ""),
    )


def _utfor_epost(nyttelast: dict) -> None:
    epost.send(nyttelast["ordre_id"], nyttelast["mal"])


UTFORERE = {"etikett": _utfor_etikett, "epost": _utfor_epost}


def arbeider(jobbtype: str, stopp: threading.Event) -> None:
    """Løkka som tømmer én kø. Kjøres i egen tråd per type.

    Etter en feil trekker den seg tilbake med doblende pause opp til
    MAKS_PAUSE. Uten det ville en sovende printer brent gjennom alle forsøk i
    løpet av sekunder, og jobbene vært døde før noen rakk å reise seg.
    """
    utfor = UTFORERE[jobbtype]
    logg.info("arbeider for %s startet", jobbtype)
    paafolgende_feil = 0

    while not stopp.is_set():
        rad = _krev(jobbtype)
        if rad is None:
            paafolgende_feil = 0
            stopp.wait(HVILE_SEK)
            continue
        try:
            utfor(json.loads(rad["nyttelast"]))
            _fullfor(rad["id"])
            paafolgende_feil = 0
        except Exception as e:  # noqa: BLE001 — alt skal fanges, køen skal leve
            handter_feil(rad, jobbtype, e)
            paafolgende_feil += 1
            pause = min(2.0 ** min(paafolgende_feil, 6), MAKS_PAUSE)
            stopp.wait(pause)

    logg.info("arbeider for %s stoppet", jobbtype)


def varmholder(stopp: threading.Event) -> None:
    """Pinger printeren jevnlig så Bluetooth-lenken ikke sovner.

    Auto-avslaget starter hele ulykken: sover printeren, dør lenken, og da
    låser den en kommunikasjonsfeil som bare strøm av og på løser.
    """
    while not stopp.is_set():
        try:
            printer.hold_varm()
        except Exception as e:  # noqa: BLE001
            logg.warning("varmholder: %s", e)
        stopp.wait(30)


def start(stopp: threading.Event) -> list[threading.Thread]:
    trader = []
    for jobbtype in UTFORERE:
        t = threading.Thread(
            target=arbeider, args=(jobbtype, stopp), name=f"jobb-{jobbtype}", daemon=True
        )
        t.start()
        trader.append(t)
    if printer.tilgjengelig():
        t = threading.Thread(
            target=varmholder, args=(stopp,), name="printer-varm", daemon=True
        )
        t.start()
        trader.append(t)
    return trader


# ── Til admin ───────────────────────────────────────────────────────────────


def kostatus() -> dict:
    with kobling() as kob:
        rader = kob.execute(
            "SELECT type, status, COUNT(*) AS n FROM jobb GROUP BY type, status"
        ).fetchall()
    ut: dict[str, dict[str, int]] = {}
    for r in rader:
        ut.setdefault(r["type"], {})[r["status"]] = r["n"]
    return ut


def feilede() -> list:
    with kobling() as kob:
        return list(
            kob.execute(
                """
                SELECT j.*, o.dagsnummer, o.kundenavn
                FROM jobb j LEFT JOIN ordre o ON o.id = j.ordre_id
                WHERE j.status = 'feilet' ORDER BY j.id DESC LIMIT 50
                """
            )
        )


def koe_paa_nytt(jobb_id: int) -> bool:
    """Legg en feilet jobb tilbake i køen. Reprint-knappen i admin."""
    with transaksjon() as kob:
        markor = kob.execute(
            "UPDATE jobb SET status = 'ny', forsok = 0, siste_feil = '', oppdatert = ?"
            " WHERE id = ? AND status IN ('feilet', 'ferdig')",
            (naa(), jobb_id),
        )
        return markor.rowcount > 0


def skriv_ut_ordre_paa_nytt(ordre_id: int) -> int:
    """Lag ferske etikettjobber for en hel ordre. Når tapen tok slutt."""
    with transaksjon() as kob:
        gamle = list(
            kob.execute(
                "SELECT nyttelast FROM jobb WHERE ordre_id = ? AND type = 'etikett'"
                " ORDER BY id",
                (ordre_id,),
            )
        )
        tid = naa()
        for rad in gamle:
            kob.execute(
                "INSERT INTO jobb (type, nyttelast, status, ordre_id, opprettet, oppdatert)"
                " VALUES ('etikett', ?, 'ny', ?, ?, ?)",
                (rad["nyttelast"], ordre_id, tid, tid),
            )
        return len(gamle)

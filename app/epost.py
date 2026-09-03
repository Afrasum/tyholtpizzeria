"""Utgående e-post. Best effort, aldri blokkerende for en bestilling.

E-posten er en formalitet: kunden står i lokalet og får nummeret ropt opp.
Derfor er den en jobb i køen framfor noe bestillingen venter på — feiler
SMTP, får kunden fortsatt nummer og kjøkkenet fortsatt etiketter.

Uten TP_SMTP_VERT logges meldingen og hoppes over. Det gjør at appen kjører
helt likt på Mac og på rpi5 uten oppsett.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from . import config
from .db import kobling
from .ordrer import med_linjer

logg = logging.getLogger("tyholt.epost")


def _kroner(ore: int) -> str:
    return f"{ore // 100} kr"


def _vipps(kob) -> tuple[str, str, str]:
    from . import innstillinger  # noqa: PLC0415 — unngår sirkulær import

    aktiv = innstillinger.aktiv_mottaker(kob)
    if aktiv is None:
        return "", "", ""
    return aktiv["navn"], aktiv["nummer"], aktiv["url"]


def _bygg(mal: str, ordre, linjer, vipps_navn: str, vipps_nummer: str,
          vipps_url: str) -> tuple[str, str]:
    nummer = ordre["dagsnummer"]
    varer = "\n".join(
        f"  {l['antall']} x {l['navn_snapshot']}" for l in linjer
    )
    if mal == "bestilling_mottatt":
        emne = f"Bestilling {nummer} – Tyholt Pizzeria"
        kropp = f"""Hei {ordre['kundenavn']}!

Vi har fått bestillingen din.

  Nummer: {nummer}

{varer}

  Å betale: {_kroner(ordre['total_ore'])}

Betal med Vipps:

  {vipps_url}

Til {vipps_navn} ({vipps_nummer}). Skriv {nummer} som melding, og vis
betalingen når du henter.

Vi roper opp nummeret ditt når pizzaen er klar.

Tyholt Pizzeria
"""
    elif mal == "klar_til_henting":
        emne = f"Nummer {nummer} er klar – Tyholt Pizzeria"
        kropp = f"""Hei {ordre['kundenavn']}!

Nummer {nummer} er klar til henting.

{varer}

Husk å vise Vipps-betalingen i kassen.

Tyholt Pizzeria
"""
    else:
        raise ValueError(f"ukjent e-postmal: {mal}")
    return emne, kropp


def send(ordre_id: int, mal: str) -> None:
    """Send én e-post. Kaster ved feil, slik at jobbkøen kan prøve på nytt."""
    with kobling() as kob:
        pakke = med_linjer(kob, ordre_id)
        if pakke is None:
            raise ValueError(f"ordre {ordre_id} finnes ikke")
        vipps_navn, vipps_nummer, vipps_url = _vipps(kob)

    ordre, linjer = pakke["ordre"], pakke["linjer"]
    if not ordre["epost"]:
        logg.info("ordre %s har ingen e-post, hopper over", ordre_id)
        return

    emne, kropp = _bygg(mal, ordre, linjer, vipps_navn, vipps_nummer, vipps_url)

    if not config.SMTP_VERT:
        logg.info(
            "SMTP ikke satt opp — ville sendt til %s: %s", ordre["epost"], emne
        )
        return

    melding = EmailMessage()
    melding["From"] = config.EPOST_FRA
    melding["To"] = ordre["epost"]
    melding["Subject"] = emne
    melding.set_content(kropp)

    with smtplib.SMTP(config.SMTP_VERT, config.SMTP_PORT, timeout=20) as smtp:
        smtp.starttls()
        if config.SMTP_BRUKER:
            smtp.login(config.SMTP_BRUKER, config.SMTP_PASSORD)
        smtp.send_message(melding)
    logg.info("e-post sendt til %s: %s", ordre["epost"], emne)

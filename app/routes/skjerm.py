"""Henteskjermen — den som står vendt mot kundene.

Kun numre. Navn hører på etiketten og i admin, ikke på en skjerm i et rom
fullt av fremmede.

To spalter: alt som ikke er klart står under «Under arbeid», og alt som er
klart står under «Klar». Skillet mellom «ny» og «i produksjon» finnes i
admin, men ikke her — for kunden er det samme sak, og nummeret skal opp på
tavla i det sekundet bestillingen er inne. Ellers står de og lurer på om den
gikk gjennom.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .. import innstillinger, ordrer
from ..db import kobling
from ..maler import maler

ruter = APIRouter()

# Alt som verken er klart, levert, forlatt eller avbrutt.
UNDER_ARBEID = ("ny", "i_produksjon")


def _tall(kob) -> dict:
    dag = ordrer.aktiv_salgsdag(kob)
    plassholdere = ",".join("?" * len(UNDER_ARBEID))
    under = [
        r["dagsnummer"]
        for r in kob.execute(
            f"SELECT dagsnummer FROM ordre WHERE salgsdag_id = ? AND skjult = 0"
            f" AND status IN ({plassholdere}) ORDER BY dagsnummer",
            (dag["id"], *UNDER_ARBEID),
        )
    ]
    return {"klare": ordrer.klare_numre(kob), "under_arbeid": under}


@ruter.get("/skjerm", response_class=HTMLResponse)
def skjerm(request: Request):
    with kobling() as kob:
        data = _tall(kob)
        return maler.TemplateResponse(
            request,
            "skjerm/skjerm.html",
            {
                "klare": data["klare"],
                "under_arbeid": data["under_arbeid"],
                "innst": innstillinger.alle(kob),
            },
        )


@ruter.get("/skjerm/data")
def skjermdata():
    with kobling() as kob:
        return _tall(kob)

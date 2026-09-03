"""Henteskjermen — den som står vendt mot kundene.

Kun numre. Navn hører på etiketten og i admin, ikke på en skjerm i et rom
fullt av fremmede.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .. import innstillinger, ordrer
from ..db import kobling
from ..maler import maler

ruter = APIRouter()


@ruter.get("/skjerm", response_class=HTMLResponse)
def skjerm(request: Request):
    with kobling() as kob:
        return maler.TemplateResponse(
            request,
            "skjerm/skjerm.html",
            {"numre": ordrer.klare_numre(kob), "innst": innstillinger.alle(kob)},
        )


@ruter.get("/skjerm/data")
def skjermdata():
    with kobling() as kob:
        dag = ordrer.gjeldende_salgsdag(kob)
        underveis = (
            [
                r["dagsnummer"]
                for r in kob.execute(
                    "SELECT dagsnummer FROM ordre WHERE salgsdag_id = ?"
                    " AND status = 'i_produksjon' ORDER BY dagsnummer",
                    (dag["id"],),
                )
            ]
            if dag
            else []
        )
        return {"klare": ordrer.klare_numre(kob), "i_produksjon": underveis}

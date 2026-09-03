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
        return {
            "klare": ordrer.klare_numre(kob),
            "i_produksjon": [
                r["dagsnummer"]
                for r in kob.execute(
                    """
                    SELECT o.dagsnummer FROM ordre o
                    JOIN salgsdag s ON s.id = o.salgsdag_id
                    WHERE o.status = 'i_produksjon' AND s.aktiv = 1
                    ORDER BY o.dagsnummer
                    """
                )
            ],
        }

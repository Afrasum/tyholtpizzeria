"""Admin: ordrekø, statusknapper, utsolgt, reprint og innstillinger.

Én side, alle knapper, alle kan gjøre alt. Det var kravet — minst mulig
friksjon for to personer i samme rom.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import allergener, auth, config, innstillinger, jobber, meny, ordrer, printer
from ..db import kobling
from ..maler import maler

ruter = APIRouter(prefix="/admin")


def _minutter_siden(tidspunkt: str) -> int:
    try:
        da = datetime.fromisoformat(tidspunkt)
    except ValueError:
        return 0
    return int((datetime.now(config.TIDSSONE) - da).total_seconds() // 60)


# ── Innlogging ──────────────────────────────────────────────────────────────


@ruter.get("/logg-inn", response_class=HTMLResponse)
def innloggingsside(request: Request, feil: str = ""):
    return maler.TemplateResponse(request, "admin/logg_inn.html", {"feil": feil})


@ruter.post("/logg-inn")
def logg_inn(passord: str = Form("")):
    if not auth.passord_stemmer(passord):
        return RedirectResponse("/admin/logg-inn?feil=1", status_code=303)
    svar = RedirectResponse("/admin", status_code=303)
    svar.set_cookie(
        auth.KAKE, auth.lag_kake(), httponly=True, samesite="lax", max_age=60 * 60 * 24
    )
    return svar


@ruter.post("/logg-ut")
def logg_ut():
    svar = RedirectResponse("/admin/logg-inn", status_code=303)
    svar.delete_cookie(auth.KAKE)
    return svar


# ── Oversikt ────────────────────────────────────────────────────────────────


@ruter.get("", response_class=HTMLResponse)
def oversikt(request: Request, _=Depends(auth.krev)):
    with kobling() as kob:
        rader = ordrer.for_admin(kob)
        dag = ordrer.aapen_salgsdag(kob)
        aapent, grunn = ordrer.kan_bestille(kob)

        for rad in rader:
            rad["minutter"] = _minutter_siden(rad["ordre"]["oppdatert"])
            rad["gammel"] = (
                rad["ordre"]["status"] == "klar"
                and rad["minutter"] >= ordrer.GAMMEL_ETTER_MIN
            )

        solgt = sum(
            l["antall"] for rad in rader for l in rad["linjer"]
            if rad["ordre"]["status"] != "avbrutt"
        )

        return maler.TemplateResponse(
            request,
            "admin/oversikt.html",
            {
                "rader": rader,
                "dag": dag,
                "aapent": aapent,
                "grunn": grunn,
                "meny": meny.full_meny(kob),
                "innst": innstillinger.alle(kob),
                "statusnavn": ordrer.STATUSNAVN,
                "flyt": ordrer.FLYT,
                "solgt": solgt,
                "feilede": jobber.feilede(),
                "kostatus": jobber.kostatus(),
                "uverifiserte": allergener.uverifiserte_ingredienser(kob),
                "gammel_etter": ordrer.GAMMEL_ETTER_MIN,
            },
        )


@ruter.get("/data")
def data(_=Depends(auth.krev)):
    """JSON for polling. Admin oppdaterer seg hvert 4. sekund."""
    with kobling() as kob:
        rader = ordrer.for_admin(kob)
        ut = []
        for rad in rader:
            o = rad["ordre"]
            minutter = _minutter_siden(o["oppdatert"])
            ut.append(
                {
                    "id": o["id"],
                    "nummer": o["dagsnummer"],
                    "navn": o["kundenavn"],
                    "status": o["status"],
                    "betalt": bool(o["betalt"]),
                    "total_ore": o["total_ore"],
                    "minutter": minutter,
                    "gammel": o["status"] == "klar" and minutter >= ordrer.GAMMEL_ETTER_MIN,
                    "linjer": [
                        {"navn": l["navn_snapshot"], "antall": l["antall"]}
                        for l in rad["linjer"]
                    ],
                    "print": {
                        "ferdig": rad["print"]["ferdig"] or 0,
                        "feilet": rad["print"]["feilet"] or 0,
                        "totalt": rad["print"]["totalt"] or 0,
                    },
                }
            )
        return {"ordrer": ut, "feilede_jobber": len(jobber.feilede())}


# ── Handlinger ──────────────────────────────────────────────────────────────


@ruter.post("/ordre/{ordre_id}/status")
def endre_status(ordre_id: int, ny: str = Form(...), _=Depends(auth.krev)):
    try:
        ordrer.sett_status(ordre_id, ny)
    except ordrer.Avvist:
        pass  # Knappen er alt borte i UI-et; en dobbelttrykk skal ikke feile stygt.
    return RedirectResponse("/admin", status_code=303)


@ruter.post("/ordre/{ordre_id}/betalt")
def endre_betalt(ordre_id: int, betalt: str = Form("1"), _=Depends(auth.krev)):
    ordrer.sett_betalt(ordre_id, betalt == "1")
    return RedirectResponse("/admin", status_code=303)


@ruter.post("/ordre/{ordre_id}/skriv-ut")
def skriv_ut_paa_nytt(ordre_id: int, _=Depends(auth.krev)):
    jobber.skriv_ut_ordre_paa_nytt(ordre_id)
    return RedirectResponse("/admin", status_code=303)


@ruter.post("/jobb/{jobb_id}/paa-nytt")
def jobb_paa_nytt(jobb_id: int, _=Depends(auth.krev)):
    jobber.koe_paa_nytt(jobb_id)
    return RedirectResponse("/admin", status_code=303)


@ruter.post("/meny/{menyelement_id}/tilgjengelig")
def bytt_tilgjengelig(
    menyelement_id: int, tilgjengelig: str = Form("1"), _=Depends(auth.krev)
):
    meny.sett_tilgjengelig(menyelement_id, tilgjengelig == "1")
    return RedirectResponse("/admin", status_code=303)


@ruter.post("/stengt")
def bytt_stengt(stengt: str = Form("0"), _=Depends(auth.krev)):
    innstillinger.sett("manuelt_stengt", "1" if stengt == "1" else "0")
    return RedirectResponse("/admin", status_code=303)


@ruter.post("/vipps")
def endre_vipps(
    vipps_navn: str = Form(""), vipps_nummer: str = Form(""), _=Depends(auth.krev)
):
    """Vipps-mottakeren skal kunne rulleres — det var et uttalt krav."""
    innstillinger.sett_mange(
        {"vipps_navn": vipps_navn.strip(), "vipps_nummer": vipps_nummer.strip()}
    )
    return RedirectResponse("/admin", status_code=303)


@ruter.get("/printerstatus")
def printerstatus(_=Depends(auth.krev)):
    return printer.status()

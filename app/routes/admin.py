"""Admin: ordrekø, statusknapper, utsolgt, reprint og innstillinger.

Én side, alle knapper, alle kan gjøre alt. Det var kravet — minst mulig
friksjon for to personer i samme rom.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from urllib.parse import quote

from .. import (
    allergener, auth, config, epost, innstillinger, jobber, meny, ordrer, printer,
)
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
def oversikt(
    request: Request,
    slettet: int | None = None,
    nullstill: str = "",
    vipps: str = "",
    eposttest: str = "",
    epostmelding: str = "",
    _=Depends(auth.krev),
):
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
                "slettet": slettet,
                "nullstill_avvist": nullstill == "avvist",
                "mottakere": innstillinger.mottakere(kob),
                "aktiv_mottaker": innstillinger.aktiv_mottaker(kob),
                "vipps_ugyldig": vipps == "ugyldig",
                "epost_resultat": eposttest,
                "epost_melding": epostmelding,
                "smtp_vert": config.SMTP_VERT,
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
        # signatur utelater minutter/gammel med vilje. De endrer seg hvert
        # minutt uansett, sa hadde de vaert med ville sida lastet pa nytt minst
        # en gang i minuttet hele kvelden — nettopp det knappetrykket midt i
        # rushet vi vil unnga. Alderen regnes ut i nettleseren i stedet.
        stabilt = [
            {k: o[k] for k in ("id", "nummer", "navn", "status", "betalt", "total_ore")}
            | {"print": o["print"], "linjer": o["linjer"]}
            for o in ut
        ]
        return {
            "ordrer": ut,
            "feilede_jobber": len(jobber.feilede()),
            "signatur": hashlib.sha256(
                json.dumps(stabilt, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest(),
        }


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


@ruter.post("/ordre/{ordre_id}/slett")
def skjul_ordre(ordre_id: int, _=Depends(auth.krev)):
    """Tar ordren ut av arbeidsflaten. Raden blir staaende i basen."""
    ordrer.skjul_ordre(ordre_id)
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
def velg_vipps(mottaker_id: str = Form(""), _=Depends(auth.krev)):
    """Bytt hvem som tar imot betalingen. Slår gjennom med én gang."""
    innstillinger.sett("vipps_mottaker_id", mottaker_id.strip())
    return RedirectResponse("/admin", status_code=303)


@ruter.post("/vipps/ny")
def ny_vipps(
    navn: str = Form(""), nummer: str = Form(""), _=Depends(auth.krev)
):
    """Legg til en mottaker. Nummeret må gi en gyldig betalingslenke."""
    navn = navn.strip()
    reint = "".join(t for t in nummer if t.isdigit())
    if not navn or not innstillinger.vipps_url(reint):
        return RedirectResponse("/admin?vipps=ugyldig", status_code=303)
    innstillinger.legg_til_mottaker(navn, reint)
    return RedirectResponse("/admin", status_code=303)


@ruter.post("/nullstill")
def nullstill(bekreft: str = Form(""), _=Depends(auth.krev)):
    """Slett alle ordrer for gjeldende salgsdag.

    Krever at ordet SLETT skrives inn. Ingen nettleserdialog — de blokkerer
    hele fanen, og da mister vi kontakten med siden.
    """
    if bekreft.strip().upper() != "SLETT":
        return RedirectResponse("/admin?nullstill=avvist", status_code=303)
    with kobling() as kob:
        dag = ordrer.gjeldende_salgsdag(kob)
    if dag is None:
        return RedirectResponse("/admin", status_code=303)
    antall = ordrer.slett_dagens_ordrer(dag["id"])
    return RedirectResponse(f"/admin?slettet={antall}", status_code=303)


@ruter.post("/epost-test")
def epost_test(til: str = Form(""), _=Depends(auth.krev)):
    ok, melding = epost.test_oppsett(til.strip())
    return RedirectResponse(
        f"/admin?eposttest={'ok' if ok else 'feil'}"
        f"&epostmelding={quote(melding[:300])}",
        status_code=303,
    )


@ruter.get("/printerstatus")
def printerstatus(_=Depends(auth.krev)):
    return printer.status()

"""Kundesida: meny, bestilling og kvittering.

KVITTERINGENE ER STENGT NAAR SIDA ER STENGT.

`/kvittering/{id}` tar en gjettbar heltallsid og viste fornavn og
e-postadresse. Det var en akseptabel pris sa lenge sida var et verktoy for én
helg, der alle som apnet en slik lenke nettopp hadde bestilt selv. Etter 4.–5.
september ligger det 208 tellbare URL-er med 119 e-postadresser bak — pa en
side som na er offentlig og skal deles. Da er prisen ikke akseptabel lenger.

Sperra henger pa `ordrer.kan_bestille()`, samme bryter som skjuler
bestillingsskjemaet, framfor pa en egen nokkel:

* na, med sida stengt, svarer alle 208 med 404
* apner vi for en ny pop-up virker kvitteringene igjen, og bestillingsveien
  er hel — den sender kunden rett hit etter `/bestill`

Prisen er at de gamle kvitteringene ogsaa blir naabare igjen ved neste
apning. Vil vi unnga det er den ekte losningen aa tomme eller anonymisere de
gamle radene foer vi apner, ikke en tredje bryter her.

Dataene rores ikke uansett: de ligger i basen og er synlige i /admin bak
passord. Det er BARE veien inn utenfra som er stengt."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from .. import allergener, innstillinger, meny, minne, ordrer
from ..db import kobling
from ..maler import maler

ruter = APIRouter()


def _forsidedata(kob, **ekstra) -> dict:
    aapent, grunn = ordrer.kan_bestille(kob)
    data = {
        "meny": meny.full_meny(kob),
        "spor": allergener.les_spor(kob),
        "aapent": aapent,
        "grunn": grunn,
        "innst": innstillinger.alle(kob),
        "maks": ordrer.MAKS_PER_BESTILLING,
        # Frosne tall fra 4.–5. september. Legges inn ALLTID, ogsaa naar det
        # er aapent: det koster et dict-oppslag, og da kan ikke malen ta 500
        # fordi noen skrudde paa den manuelle bryteren.
        **minne.alt(),
    }
    data.update(ekstra)
    return data


@ruter.get("/", response_class=HTMLResponse)
def forside(request: Request):
    with kobling() as kob:
        return maler.TemplateResponse(request, "kunde/forside.html", _forsidedata(kob))


@ruter.post("/bestill")
async def bestill(request: Request):
    """Tar imot bestillingsskjemaet.

    Ruta er async fordi antall-feltene er dynamiske (`antall_<id>` per rett),
    og da må hele skjemaet leses med `await request.form()`. Selve
    ordreopprettelsen er synkron SQLite, så den kjøres i trådpoolen framfor å
    blokkere hendelsesløkka.
    """
    skjema = await request.form()

    kundenavn = str(skjema.get("kundenavn", ""))
    epost = str(skjema.get("epost", ""))
    # required i HTML-en er ikke en kontroll — den kan omgaas trivielt.
    # Avkrysningen ER hele artefaktet av «de lover aa betale», sa den maa
    # sjekkes her.
    lofte = str(skjema.get("lofte", "")).strip() != ""

    onsker: list[ordrer.Onske] = []
    for nokkel, verdi in skjema.multi_items():
        if not nokkel.startswith("antall_"):
            continue
        try:
            menyelement_id = int(nokkel.removeprefix("antall_"))
            antall = int(str(verdi) or 0)
        except ValueError:
            continue
        if antall > 0:
            onsker.append(ordrer.Onske(menyelement_id, antall))

    try:
        if not lofte:
            raise ordrer.Avvist(
                "Du må krysse av for at du henter og betaler med Vipps."
            )
        res = await run_in_threadpool(ordrer.opprett, kundenavn, epost, onsker)
    except ordrer.Avvist as e:
        def _feilside():
            with kobling() as kob:
                return maler.TemplateResponse(
                    request,
                    "kunde/forside.html",
                    _forsidedata(
                        kob,
                        feil=str(e),
                        forrige_navn=kundenavn,
                        forrige_epost=epost,
                        forrige_antall={
                            o.menyelement_id: o.antall for o in onsker
                        },
                    ),
                    status_code=400,
                )

        return await run_in_threadpool(_feilside)

    return RedirectResponse(f"/kvittering/{res['ordre_id']}", status_code=303)


def _stengt_for_kvittering(kob) -> bool:
    """Sant naar kvitteringene ikke skal vaere naabare. Se modulen over."""
    aapent, _ = ordrer.kan_bestille(kob)
    return not aapent


@ruter.get("/kvittering/{ordre_id}", response_class=HTMLResponse)
def kvittering(request: Request, ordre_id: int):
    with kobling() as kob:
        pakke = None if _stengt_for_kvittering(kob) else ordrer.med_linjer(kob, ordre_id)
        if pakke is None:
            return maler.TemplateResponse(
                request,
                "kunde/ikke_funnet.html",
                {"innst": innstillinger.alle(kob)},
                status_code=404,
            )
        return maler.TemplateResponse(
            request,
            "kunde/kvittering.html",
            {
                "ordre": pakke["ordre"],
                "linjer": pakke["linjer"],
                "innst": innstillinger.alle(kob),
                "statusnavn": ordrer.KUNDESTATUS,
            },
        )


@ruter.get("/status/{ordre_id}")
def status(ordre_id: int):
    """JSON for kvitteringssida, som poller for å se når pizzaen er klar.

    Stenges sammen med kvitteringen: den lakk dagsnummer og status per id.
    """
    with kobling() as kob:
        if _stengt_for_kvittering(kob):
            return {"finnes": False}
        rad = kob.execute(
            "SELECT dagsnummer, status FROM ordre WHERE id = ?", (ordre_id,)
        ).fetchone()
    if rad is None:
        return {"finnes": False}
    return {
        "finnes": True,
        "nummer": rad["dagsnummer"],
        "status": rad["status"],
        "statusnavn": ordrer.KUNDESTATUS.get(rad["status"], rad["status"]),
    }

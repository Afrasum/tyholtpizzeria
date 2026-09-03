"""FastAPI-appen. Setter opp basen, starter arbeiderne, monterer rutene.

Kjøres med ÉN uvicorn-arbeider. Det er ikke valgfritt: tildelingen av
dagsnummer bygger på SQLites skrivelås i én prosess, og printeren tåler bare
én tilkobling om gangen.
"""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import config, db, jobber, seed
from .maler import MALKATALOG
from .routes import admin, kunde, skjerm

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
logg = logging.getLogger("tyholt")

_stopp = threading.Event()


@asynccontextmanager
async def livsløp(app: FastAPI):
    db.klargjor()
    seed.kjor()
    logg.info("base klar: %s", config.DB_STI)

    trader = jobber.start(_stopp)
    logg.info("startet %s arbeidere", len(trader))
    try:
        yield
    finally:
        _stopp.set()
        for t in trader:
            t.join(timeout=5)
        logg.info("arbeidere stoppet")


app = FastAPI(title="Tyholt Pizzeria", lifespan=livsløp, docs_url=None, redoc_url=None)

app.mount(
    "/static", StaticFiles(directory=str(MALKATALOG.parent / "static")), name="static"
)

app.include_router(kunde.ruter)
app.include_router(admin.ruter)
app.include_router(skjerm.ruter)


@app.get("/helse")
def helse():
    """Til overvåking og til å se at prosessen faktisk lever."""
    return {"ok": True, "ko": jobber.kostatus()}

"""Jinja2-oppsett, ett sted.

Malene er plassholdere med vilje: semantisk HTML og tydelige klassenavn, slik
at de kan restyles uten å røre logikken.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

MALKATALOG = Path(__file__).resolve().parent / "templates"

maler = Jinja2Templates(directory=str(MALKATALOG))


def _kroner(ore: int) -> str:
    """59 kr, ikke 59.0 kr. Heltall inn, heltall ut."""
    if ore % 100 == 0:
        return f"{ore // 100} kr"
    return f"{ore / 100:.2f}".replace(".", ",") + " kr"


maler.env.filters["kroner"] = _kroner


# Cloudflare cacher /static i fire timer (max-age=14400). Uten en
# versjonsnokkel kan en telefon som allerede har lastet sida fa ny HTML servert
# sammen med et fire timer gammelt stilark — midt i service. Nokkelen er
# mtime pa den nyeste statiske fila, lest en gang ved oppstart. Deploy
# restarter tjenesten, sa den folger med av seg selv.
STATISKKATALOG = Path(__file__).resolve().parent / "static"


def _statiskversjon() -> str:
    nyeste = max(
        (f.stat().st_mtime for f in STATISKKATALOG.rglob("*") if f.is_file()),
        default=0.0,
    )
    return str(int(nyeste))


maler.env.globals["statiskversjon"] = _statiskversjon()

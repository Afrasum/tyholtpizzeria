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

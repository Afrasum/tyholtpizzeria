"""Admin-innlogging: ett passord, signert informasjonskapsel.

Ingen brukere, ingen roller, ingen adgangskontroll utover dette — det var
avklart. Alle som skal inn bak disken bruker samme passord og kan gjøre alt.

Passordet sammenlignes med compare_digest for å unngå at svartiden lekker
hvor mange tegn som stemte. Det er billig å gjøre riktig.
"""

from __future__ import annotations

import secrets

from fastapi import HTTPException, Request, status
from itsdangerous import BadSignature, URLSafeSerializer

from . import config

KAKE = "tyholt_admin"
_signerer = URLSafeSerializer(config.HEMMELIG_NOKKEL, salt="admin")


def passord_stemmer(kandidat: str) -> bool:
    return secrets.compare_digest(kandidat or "", config.ADMIN_PASSORD)


def lag_kake() -> str:
    return _signerer.dumps({"innlogget": True})


def er_innlogget(request: Request) -> bool:
    raa = request.cookies.get(KAKE)
    if not raa:
        return False
    try:
        return bool(_signerer.loads(raa).get("innlogget"))
    except BadSignature:
        return False


def krev(request: Request) -> None:
    """FastAPI-avhengighet. Sender uinnloggede til innloggingssida."""
    if not er_innlogget(request):
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/admin/logg-inn"},
        )

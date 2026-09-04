"""SQLite-tilgang. Én fil, WAL, ingen ORM.

Hver forespørsel får sin egen kobling via `kobling()`. FastAPI-rutene er
synkrone (`def`, ikke `async def`) nettopp fordi sqlite3 blokkerer — da kjører
de i trådpoolen og stopper ikke hendelsesløkken.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from . import config

SKJEMA = Path(__file__).resolve().parent / "schema.sql"


def naa() -> str:
    """Tidspunkt som ISO-8601 med tidssone. Alle tider i basen ser slik ut."""
    return datetime.now(config.TIDSSONE).isoformat(timespec="seconds")


def _koble(sti: Path) -> sqlite3.Connection:
    kob = sqlite3.connect(sti, timeout=10.0, isolation_level=None)
    kob.row_factory = sqlite3.Row
    kob.execute("PRAGMA foreign_keys = ON")
    kob.execute("PRAGMA busy_timeout = 10000")
    return kob


@contextmanager
def kobling() -> Iterator[sqlite3.Connection]:
    """Lesekobling. Autocommit — bruk `transaksjon()` for skriving."""
    kob = _koble(config.DB_STI)
    try:
        yield kob
    finally:
        kob.close()


@contextmanager
def transaksjon() -> Iterator[sqlite3.Connection]:
    """Skrivekobling med BEGIN IMMEDIATE.

    IMMEDIATE tar skrivelåsen med én gang framfor å oppgradere underveis. Det
    er det som gjør tildeling av dagsnummer trygg: to samtidige bestillinger
    kan ikke lese samme MAX(dagsnummer).
    """
    kob = _koble(config.DB_STI)
    try:
        kob.execute("BEGIN IMMEDIATE")
        yield kob
        kob.execute("COMMIT")
    except Exception:
        kob.execute("ROLLBACK")
        raise
    finally:
        kob.close()


# Kolonner lagt til etter at basen forst ble tatt i bruk. CREATE TABLE IF NOT
# EXISTS rorer ikke en tabell som alt finnes, sa disse ma legges til for seg.
TILLEGGSKOLONNER: tuple[tuple[str, str, str], ...] = (
    ("salgsdag", "startnummer", "INTEGER NOT NULL DEFAULT 1"),
    # Hoyeste nummer som NOEN GANG er delt ut denne dagen. Staar her og ikke
    # utledes fra ordre-tabellen, fordi en slettet ordre ellers ville frigjort
    # nummeret sitt til neste kunde.
    ("salgsdag", "sistenummer", "INTEGER NOT NULL DEFAULT 0"),
)


def klargjor() -> None:
    """Lag katalog og tabeller. Idempotent, kjøres ved hver oppstart."""
    config.DB_STI.parent.mkdir(parents=True, exist_ok=True)
    kob = _koble(config.DB_STI)
    try:
        kob.executescript(SKJEMA.read_text(encoding="utf-8"))
        for tabell, kolonne, type_ in TILLEGGSKOLONNER:
            finnes = {
                r["name"] for r in kob.execute(f"PRAGMA table_info({tabell})")
            }
            if kolonne not in finnes:
                kob.execute(f"ALTER TABLE {tabell} ADD COLUMN {kolonne} {type_}")
    finally:
        kob.close()

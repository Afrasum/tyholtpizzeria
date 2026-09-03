"""Tester for tilstanden NAAR DET ER STENGT.

Alle de andre testene kaller _tving_apent() forst, sa ingen av dem roerer
denne stien. Det er nettopp her feilen laa: klokka 00:00 pa den 5. stenger
dag 1, og da skal ikke ordrer som fortsatt er klare forsvinne fra admin og
henteskjermen.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _oppsett(tmp_path, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "DB_STI", tmp_path / "test.db")
    from app import db, seed

    db.klargjor()
    seed.kjor()
    return db


def _legg_ordre_paa_dag(db, dato: str, navn: str = "Afras") -> int:
    """Lag en ordre direkte pa en gitt salgsdag, uten aa gaa via klokka."""
    from app.db import naa

    with db.transaksjon() as kob:
        dag = kob.execute("SELECT id FROM salgsdag WHERE dato = ?", (dato,)).fetchone()
        rett = kob.execute(
            "SELECT * FROM menyelement WHERE slug = 'margherita'"
        ).fetchone()
        neste = kob.execute(
            "SELECT COALESCE(MAX(dagsnummer), 0) + 1 AS n FROM ordre WHERE salgsdag_id = ?",
            (dag["id"],),
        ).fetchone()["n"]
        tid = naa()
        markor = kob.execute(
            "INSERT INTO ordre (salgsdag_id, dagsnummer, kundenavn, status, betalt,"
            " total_ore, opprettet, oppdatert) VALUES (?, ?, ?, 'klar', 0, ?, ?, ?)",
            (dag["id"], neste, navn, rett["pris_ore"], tid, tid),
        )
        ordre_id = int(markor.lastrowid)
        kob.execute(
            "INSERT INTO ordrelinje (ordre_id, menyelement_id, navn_snapshot,"
            " etikett_snapshot, pris_ore_snapshot, antall) VALUES (?, ?, ?, ?, ?, 1)",
            (ordre_id, rett["id"], rett["navn"], rett["etikettnavn"], rett["pris_ore"]),
        )
        return ordre_id


def test_midnatt_er_fortsatt_apent_pga_slakken(tmp_path, monkeypatch):
    """stenger star pa 01:00, ikke 00:00.

    Blir det et kvarter pa overtid skal ikke bestilling og admin falle sammen
    mens det star folk i lokalet. Den manuelle stengt-bryteren er den ekte
    stengingen.
    """
    db = _oppsett(tmp_path, monkeypatch)
    from app import ordrer

    midnatt = datetime.fromisoformat("2026-09-05T00:15:00+02:00")
    with db.kobling() as kob:
        dag = ordrer.aapen_salgsdag(kob, midnatt)
    assert dag is not None and dag["dato"] == "2026-09-04"


def test_admin_viser_dag1_ordrer_naar_dagen_er_over(tmp_path, monkeypatch):
    """01:30 pa den 5.: dag 1 er stengt, dag 2 har ikke apnet.

    Ordrer fra dag 1 som fortsatt er klare MAA vises. Uten fiksen faller
    for_admin tilbake pa nyeste salgsdag (den 5.), som er tom - og da blir
    bade admin og henteskjermen svart mens det star upplukkede pizzaer.
    """
    db = _oppsett(tmp_path, monkeypatch)
    from app import ordrer

    _legg_ordre_paa_dag(db, "2026-09-04", "Afras")
    etter = datetime.fromisoformat("2026-09-05T01:30:00+02:00")

    with db.kobling() as kob:
        assert ordrer.aapen_salgsdag(kob, etter) is None, "skal vaere stengt"
        rader = ordrer.for_admin(kob, tid=etter)

    assert len(rader) == 1, "dag 1-ordren forsvant fra admin"
    assert rader[0]["ordre"]["kundenavn"] == "Afras"


def test_henteskjerm_viser_klare_ordrer_etter_stengetid(tmp_path, monkeypatch):
    """Nummeret skal sta pa skjermen selv om klokka har passert stengetid."""
    db = _oppsett(tmp_path, monkeypatch)
    from app import ordrer

    _legg_ordre_paa_dag(db, "2026-09-04", "Afras")
    etter = datetime.fromisoformat("2026-09-05T01:30:00+02:00")

    with db.kobling() as kob:
        assert ordrer.klare_numre(kob, tid=etter) == [1], (
            "kunden mistet nummeret sitt idet vi stengte"
        )


def test_admin_er_tom_men_ikke_forvirrende_for_apning(tmp_path, monkeypatch):
    """14:00 pa den 4.: ingen dag har apnet ennaa, ingen ordrer finnes."""
    db = _oppsett(tmp_path, monkeypatch)
    from app import ordrer

    foer = datetime.fromisoformat("2026-09-04T14:00:00+02:00")
    with db.kobling() as kob:
        assert ordrer.aapen_salgsdag(kob, foer) is None
        assert ordrer.for_admin(kob, tid=foer) == []


def test_dag2_ordrer_vises_ikke_pa_dag1(tmp_path, monkeypatch):
    """Salgsdagene skal holdes fra hverandre."""
    db = _oppsett(tmp_path, monkeypatch)
    from app import ordrer

    _legg_ordre_paa_dag(db, "2026-09-04", "Dag1")
    _legg_ordre_paa_dag(db, "2026-09-05", "Dag2")

    i_dag1 = datetime.fromisoformat("2026-09-04T20:00:00+02:00")
    with db.kobling() as kob:
        rader = ordrer.for_admin(kob, tid=i_dag1)
    assert [r["ordre"]["kundenavn"] for r in rader] == ["Dag1"]


def test_bestilling_er_apen_utenfor_apningstid(tmp_path, monkeypatch):
    """Klokka er ikke en sperre — bare den manuelle bryteren er.

    Dette er et driftskrav: vi ma kunne teste dagen for, og et kvarter pa
    overtid skal ikke kreve SQL for a redde.
    """
    db = _oppsett(tmp_path, monkeypatch)
    from app.ordrer import Onske, opprett

    with db.kobling() as kob:
        eid = kob.execute(
            "SELECT id FROM menyelement WHERE slug='margherita'"
        ).fetchone()["id"]
        from app import ordrer

        assert ordrer.aapen_salgsdag(kob) is None, "3. sept: ingen salgsdag apen"
        assert ordrer.kan_bestille(kob)[0] is True, "skal likevel vaere apent"

    res = opprett("Tester", None, [Onske(eid, 1)])
    assert res["nummer"] >= 1


def test_numrene_starter_tosifret_ikke_paa_en(tmp_path, monkeypatch):
    """Forste ordre skal ikke vaere «nummer 1».

    Et tosifret starttall ser ut som vi har holdt pa en stund. Numrene skal
    fortsatt ga oppover en om gangen derfra.
    """
    db = _oppsett(tmp_path, monkeypatch)
    from app import ordrer
    from app.ordrer import Onske, opprett

    with db.kobling() as kob:
        eid = kob.execute(
            "SELECT id FROM menyelement WHERE slug='margherita'"
        ).fetchone()["id"]
        dag = ordrer.gjeldende_salgsdag(kob) or ordrer.salgsdag_for_ordre(kob)

    forste = opprett("A", None, [Onske(eid, 1)])["nummer"]
    andre = opprett("B", None, [Onske(eid, 1)])["nummer"]

    assert 11 <= forste <= 47, f"startnummer {forste} er utenfor omradet"
    assert andre == forste + 1


def test_nummer_over_999_begynner_forfra(tmp_path, monkeypatch):
    """Fire siffer far ikke plass stort pa 12 mm tape."""
    db = _oppsett(tmp_path, monkeypatch)
    from app import ordrer
    from app.ordrer import Onske, opprett

    with db.kobling() as kob:
        eid = kob.execute(
            "SELECT id FROM menyelement WHERE slug='margherita'"
        ).fetchone()["id"]

    # Sett dagen rett under taket.
    with db.transaksjon() as kob:
        dag = ordrer.salgsdag_for_ordre(kob)
        kob.execute(
            "UPDATE salgsdag SET startnummer = ? WHERE id = ?",
            (ordrer.MAKS_DAGSNUMMER, dag["id"]),
        )

    assert opprett("A", None, [Onske(eid, 1)])["nummer"] == 999
    assert opprett("B", None, [Onske(eid, 1)])["nummer"] == 1
    assert opprett("C", None, [Onske(eid, 1)])["nummer"] == 2

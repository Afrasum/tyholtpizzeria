"""Tester for det sammenhengende lopet.

Salgsdager var opprinnelig en rad per dato, med en teller som startet forfra
hver dag. Filen som la her het test_stengt.py og beskrev dagsvekslingen: hva
som skulle skje klokka 00:00 den 5., og hvordan admin ikke skulle bli tom for
apning. Det er borte. Na finnes det ETT lop, og disse testene beskriver
garantiene det gir i stedet.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _oppsett(tmp_path, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "DB_STI", tmp_path / "test.db")
    from app import db, seed

    db.klargjor()
    seed.kjor()
    return db


def _meny_id(db, slug="margherita"):
    with db.kobling() as kob:
        return kob.execute(
            "SELECT id FROM menyelement WHERE slug = ?", (slug,)
        ).fetchone()["id"]


def test_bestilling_er_apen_uansett_hva_klokka_er(tmp_path, monkeypatch):
    """Klokka er ikke en sperre. Bare bryteren i admin er.

    Var apningstiden kodet, kunne vi ikke testet dagen for, og et kvarter pa
    overtid krevde SQL for a redde.
    """
    db = _oppsett(tmp_path, monkeypatch)
    from app import ordrer
    from app.ordrer import Onske, opprett

    with db.kobling() as kob:
        aapent, grunn = ordrer.kan_bestille(kob)
    assert aapent is True and grunn == ""
    assert opprett("Afras", None, [Onske(_meny_id(db), 1)])["nummer"] >= 11

    with db.transaksjon() as kob:
        kob.execute("UPDATE innstilling SET verdi='1' WHERE nokkel='manuelt_stengt'")
    with db.kobling() as kob:
        aapent, grunn = ordrer.kan_bestille(kob)
    assert aapent is False and "stengt" in grunn


def test_ingenting_forsvinner_av_seg_selv(tmp_path, monkeypatch):
    """Kjernegarantien. Dette var feilen dagsmodellen hadde.

    En ordre som fortsatt er klar skal sta i admin og pa tavla til noen
    faktisk trykker levert - uansett hvor mange ganger klokka har passert
    midnatt siden den ble lagt inn.
    """
    db = _oppsett(tmp_path, monkeypatch)
    from app import ordrer
    from app.ordrer import Onske, opprett, sett_status

    res = opprett("Glemt Kunde", None, [Onske(_meny_id(db), 1)])
    sett_status(res["ordre_id"], "klar")

    # Flytt ordren langt bakover i tid. Med dagsmodellen ville den vaert borte.
    with db.transaksjon() as kob:
        kob.execute(
            "UPDATE ordre SET opprettet = '2026-09-01T18:00:00+02:00',"
            " oppdatert = '2026-09-01T18:00:00+02:00' WHERE id = ?",
            (res["ordre_id"],),
        )

    with db.kobling() as kob:
        assert [r["ordre"]["dagsnummer"] for r in ordrer.for_admin(kob)] == [
            res["nummer"]
        ]
        assert ordrer.klare_numre(kob) == [res["nummer"]]


def test_numrene_starter_tosifret_ikke_paa_en(tmp_path, monkeypatch):
    """«Nummer 1» avslorer at vi nettopp apnet. Et tosifret tall gjor ikke det."""
    db = _oppsett(tmp_path, monkeypatch)
    from app import ordrer
    from app.ordrer import Onske, opprett

    with db.kobling() as kob:
        start = ordrer.aktiv_salgsdag(kob)["startnummer"]
    assert 11 <= start <= 47
    assert opprett("Forste", None, [Onske(_meny_id(db), 1)])["nummer"] == start


def test_nummer_over_999_begynner_forfra(tmp_path, monkeypatch):
    """Fire siffer blir for smatt pa 12 mm tape, sa vi tar det laveste ledige."""
    db = _oppsett(tmp_path, monkeypatch)
    from app import ordrer
    from app.ordrer import Onske, opprett

    eid = _meny_id(db)
    with db.transaksjon() as kob:
        dag = ordrer.aktiv_salgsdag(kob)
        kob.execute(
            "UPDATE salgsdag SET startnummer = 999, sistenummer = 998 WHERE id = ?",
            (dag["id"],),
        )
    assert opprett("A", None, [Onske(eid, 1)])["nummer"] == 999
    assert opprett("B", None, [Onske(eid, 1)])["nummer"] == 1
    assert opprett("C", None, [Onske(eid, 1)])["nummer"] == 2


def test_lopet_er_stabilt_over_omstart(tmp_path, monkeypatch):
    """seed kjores ved hver oppstart og skal peke pa samme rad hver gang."""
    db = _oppsett(tmp_path, monkeypatch)
    from app import ordrer, seed
    from app.ordrer import Onske, opprett

    res = opprett("Afras", None, [Onske(_meny_id(db), 1)])
    with db.kobling() as kob:
        forst = ordrer.aktiv_salgsdag(kob)["id"]

    for _ in range(3):
        seed.kjor()

    with db.kobling() as kob:
        assert ordrer.aktiv_salgsdag(kob)["id"] == forst
        assert [r["ordre"]["dagsnummer"] for r in ordrer.for_admin(kob)] == [
            res["nummer"]
        ]
    assert opprett("Kari", None, [Onske(_meny_id(db), 1)])["nummer"] == res["nummer"] + 1


def test_oppgradering_fra_dagsmodellen_beholder_ordrene(tmp_path, monkeypatch):
    """Det risikable ved endringen: gamle ordrer skal ikke bli usynlige.

    Basen i drift har flere daterte salgsdager, og kveldens ordrer ligger pa
    en av dem. Velger vi feil rad naar lopet skal pekes ut, forsvinner de fra
    bade admin og tavla i det koden tas i bruk.
    """
    db = _oppsett(tmp_path, monkeypatch)
    from app import ordrer, seed
    from app.db import naa

    # Bygg opp den gamle formen: flere daterte rader, ordren pa den siste,
    # og ingen peker satt.
    with db.transaksjon() as kob:
        kob.execute("DELETE FROM innstilling WHERE nokkel = 'salgsdag_id'")
        kob.execute("DELETE FROM ordre")
        for dato in ("2026-09-03", "2026-09-04", "2026-09-05"):
            kob.execute(
                "INSERT INTO salgsdag (dato, apner, stenger, aktiv, startnummer)"
                " VALUES (?, ?, ?, 1, 46) ON CONFLICT(dato) DO NOTHING",
                (dato, f"{dato}T15:00:00+02:00", f"{dato}T23:59:00+02:00"),
            )
        kveldens = kob.execute(
            "SELECT id FROM salgsdag WHERE dato = '2026-09-04'"
        ).fetchone()["id"]
        rett = kob.execute("SELECT * FROM menyelement LIMIT 1").fetchone()
        tid = naa()
        markor = kob.execute(
            "INSERT INTO ordre (salgsdag_id, dagsnummer, kundenavn, status, betalt,"
            " total_ore, opprettet, oppdatert) VALUES (?, 57, 'Kveldens', 'klar', 0,"
            " ?, ?, ?)",
            (kveldens, rett["pris_ore"], tid, tid),
        )
        kob.execute(
            "INSERT INTO ordrelinje (ordre_id, menyelement_id, navn_snapshot,"
            " etikett_snapshot, pris_ore_snapshot, antall) VALUES (?, ?, ?, ?, ?, 1)",
            (markor.lastrowid, rett["id"], rett["navn"], rett["etikettnavn"],
             rett["pris_ore"]),
        )

    seed.kjor()   # som ved oppstart etter deploy

    with db.kobling() as kob:
        assert ordrer.aktiv_salgsdag(kob)["id"] == kveldens, "valgte feil rad"
        assert [r["ordre"]["dagsnummer"] for r in ordrer.for_admin(kob)] == [57]
        assert ordrer.klare_numre(kob) == [57]
        assert ordrer.solgte_pizzaer(kob) == 1


def test_nullstill_setter_startpunktet_for_tellinga(tmp_path, monkeypatch):
    """«N pizzaer» teller fra sist «Nullstill dagen», ikke fra tidenes morgen."""
    db = _oppsett(tmp_path, monkeypatch)
    from app import ordrer
    from app.ordrer import Onske, opprett

    eid = _meny_id(db)
    for navn in ("A", "B"):
        opprett(navn, None, [Onske(eid, 2)])
    with db.kobling() as kob:
        assert ordrer.solgte_pizzaer(kob) == 4
        dag = ordrer.aktiv_salgsdag(kob)

    ordrer.skjul_alle(dag["id"])
    with db.kobling() as kob:
        assert ordrer.solgte_pizzaer(kob) == 0, "ny dag begynner pa null"
        assert ordrer.for_admin(kob) == []
        assert len(ordrer.skjulte_for_admin(kob)) == 2, "men radene ligger der"

    opprett("C", None, [Onske(eid, 3)])
    with db.kobling() as kob:
        assert ordrer.solgte_pizzaer(kob) == 3

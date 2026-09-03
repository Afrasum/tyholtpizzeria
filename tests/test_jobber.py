"""Tester for jobbkøen — krav, retry, oppgi og reprint."""

from __future__ import annotations

import json
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _oppsett(tmp_path, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "DB_STI", tmp_path / "test.db")
    from app import db, seed

    db.klargjor()
    seed.kjor()
    nu = datetime.now(config.TIDSSONE)
    with db.transaksjon() as kob:
        kob.execute("UPDATE salgsdag SET aktiv = 0")
        kob.execute(
            "UPDATE salgsdag SET aktiv = 1, apner = ?, stenger = ? WHERE dato = ?",
            (
                nu.replace(hour=0, minute=1).isoformat(timespec="seconds"),
                nu.replace(hour=23, minute=59).isoformat(timespec="seconds"),
                "2026-09-04",
            ),
        )
    return db


def _ordre(db, antall=1):
    from app.ordrer import Onske, opprett

    with db.kobling() as kob:
        eid = kob.execute(
            "SELECT id FROM menyelement WHERE slug = 'margherita'"
        ).fetchone()["id"]
    return opprett("Afras", None, [Onske(eid, antall)])


def _kjor_til_tom(jobbtype, grense=60):
    """Kjør arbeideren til køen er tom, uten å vente på hviletiden."""
    from app import jobber

    for _ in range(grense):
        rad = jobber._krev(jobbtype)
        if rad is None:
            return
        try:
            jobber.UTFORERE[jobbtype](json.loads(rad["nyttelast"]))
            jobber._fullfor(rad["id"])
        except Exception as e:
            jobber._feil(rad["id"], jobbtype, rad["forsok"], f"{type(e).__name__}: {e}")


def test_strimmelen_printes_i_en_jobb_med_alle_etikettene(tmp_path, monkeypatch):
    db = _oppsett(tmp_path, monkeypatch)
    from app import jobber

    printet = []
    monkeypatch.setattr(jobber.printer, "skriv_ut", lambda **kw: printet.append(kw))

    _ordre(db, antall=3)
    _kjor_til_tom("etikett")

    assert len(printet) == 1, "3 pizzaer skal bli EN utskrift"
    ets = printet[0]["etiketter"]
    assert [e["indeks"] for e in ets] == [1, 2, 3]
    assert all(e["av"] == 3 for e in ets)
    with db.kobling() as kob:
        n = kob.execute(
            "SELECT COUNT(*) c FROM jobb WHERE type='etikett' AND status='ferdig'"
        ).fetchone()["c"]
    assert n == 1


def test_printerfeil_gir_retry_og_deretter_feilet(tmp_path, monkeypatch):
    db = _oppsett(tmp_path, monkeypatch)
    from app import config, jobber, printer

    monkeypatch.setattr(config, "PRINT_MAKS_FORSOK", 3)
    monkeypatch.setattr(jobber, "MAKS_FORSOK", {"etikett": 3, "epost": 3})

    forsok = []

    def alltid_feil(**kw):
        forsok.append(kw)
        raise printer.PrinterFeil("printeren sover")

    monkeypatch.setattr(jobber.printer, "skriv_ut", alltid_feil)

    _ordre(db, antall=1)
    _kjor_til_tom("etikett")

    # Ett forsøk per runde til den gir opp: tre i alt.
    assert len(forsok) == 3
    with db.kobling() as kob:
        rad = kob.execute(
            "SELECT status, forsok, siste_feil FROM jobb WHERE type='etikett'"
        ).fetchone()
    assert rad["status"] == "feilet"
    assert rad["forsok"] == 3
    assert "sover" in rad["siste_feil"]


def test_forbigaaende_feil_lykkes_paa_andre_forsok(tmp_path, monkeypatch):
    db = _oppsett(tmp_path, monkeypatch)
    from app import jobber, printer

    kall = {"n": 0}

    def flakete(**kw):
        kall["n"] += 1
        if kall["n"] == 1:
            raise printer.PrinterFeil("forbigående")

    monkeypatch.setattr(jobber.printer, "skriv_ut", flakete)

    _ordre(db, antall=1)
    _kjor_til_tom("etikett")

    assert kall["n"] == 2
    with db.kobling() as kob:
        rad = kob.execute(
            "SELECT status, forsok FROM jobb WHERE type='etikett'"
        ).fetchone()
    assert rad["status"] == "ferdig"
    assert rad["forsok"] == 1


def test_krev_gir_hver_jobb_til_bare_en_arbeider(tmp_path, monkeypatch):
    """To arbeidere skal aldri kunne printe samme etikett."""
    db = _oppsett(tmp_path, monkeypatch)
    from app import jobber

    for _ in range(5):
        _ordre(db, antall=1)   # fem ordrer gir fem jobber

    tatt: list[int] = []
    laas = threading.Lock()

    def hoster():
        while True:
            rad = jobber._krev("etikett")
            if rad is None:
                return
            with laas:
                tatt.append(rad["id"])
            time.sleep(0.001)

    trader = [threading.Thread(target=hoster) for _ in range(4)]
    for t in trader:
        t.start()
    for t in trader:
        t.join(timeout=10)

    assert len(tatt) == 5
    assert len(set(tatt)) == 5, "samme jobb ble tatt to ganger"


def test_epostko_stoppes_ikke_av_hengt_printer(tmp_path, monkeypatch):
    """Kjernen i å ha to arbeidere: køene er uavhengige."""
    db = _oppsett(tmp_path, monkeypatch)
    from app import jobber, printer

    monkeypatch.setattr(
        jobber.printer, "skriv_ut",
        lambda **kw: (_ for _ in ()).throw(printer.PrinterFeil("henger")),
    )
    sendt = []
    monkeypatch.setattr(jobber.epost, "send", lambda oid, mal: sendt.append(mal))

    from app.ordrer import Onske, opprett

    with db.kobling() as kob:
        eid = kob.execute(
            "SELECT id FROM menyelement WHERE slug='margherita'"
        ).fetchone()["id"]
    opprett("Afras", "a@example.com", [Onske(eid, 1)])

    _kjor_til_tom("etikett")   # feiler fullstendig
    _kjor_til_tom("epost")     # skal likevel gå gjennom

    assert sendt == ["bestilling_mottatt"]


def test_reprint_lager_ferske_jobber(tmp_path, monkeypatch):
    db = _oppsett(tmp_path, monkeypatch)
    from app import jobber

    monkeypatch.setattr(jobber.printer, "skriv_ut", lambda **kw: None)
    res = _ordre(db, antall=2)
    _kjor_til_tom("etikett")

    lagt = jobber.skriv_ut_ordre_paa_nytt(res["ordre_id"])
    assert lagt == 1, "reprint av ordren er en ny strimmeljobb"
    with db.kobling() as kob:
        rad = kob.execute(
            "SELECT nyttelast FROM jobb WHERE type='etikett' AND status='ny'"
        ).fetchone()
    assert len(json.loads(rad["nyttelast"])["etiketter"]) == 2


def test_koe_paa_nytt_paa_enkeltjobb(tmp_path, monkeypatch):
    db = _oppsett(tmp_path, monkeypatch)
    from app import jobber, printer

    monkeypatch.setattr(jobber, "MAKS_FORSOK", {"etikett": 1, "epost": 1})
    monkeypatch.setattr(
        jobber.printer, "skriv_ut",
        lambda **kw: (_ for _ in ()).throw(printer.PrinterFeil("tom for tape")),
    )
    _ordre(db, antall=1)
    _kjor_til_tom("etikett")

    feilede = jobber.feilede()
    assert len(feilede) == 1
    assert "tape" in feilede[0]["siste_feil"]

    assert jobber.koe_paa_nytt(feilede[0]["id"]) is True
    with db.kobling() as kob:
        rad = kob.execute("SELECT status, forsok FROM jobb").fetchone()
    assert rad["status"] == "ny" and rad["forsok"] == 0

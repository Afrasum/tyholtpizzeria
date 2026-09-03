"""Tester for ordrelogikken — nummertildeling, statusflyt og avvisning.

Kjøres med: .venv/bin/python -m pytest tests -q
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _oppsett(tmp_path, monkeypatch):
    """Fersk base per test. config leses ved import, så vi må patche etterpå."""
    from app import config

    monkeypatch.setattr(config, "DB_STI", tmp_path / "test.db")
    from app import db, seed

    db.klargjor()
    seed.kjor()
    return db


def _apen_tid():
    """Et tidspunkt inne i salgsdagen 4. september."""
    return datetime.fromisoformat("2026-09-04T18:00:00+02:00")


def _tving_apent(db):
    """Flytt salgsdagen slik at «nå» er inne i den, uansett når testen kjører."""
    from app import config

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


def _meny_id(db, slug):
    with db.kobling() as kob:
        return kob.execute(
            "SELECT id FROM menyelement WHERE slug = ?", (slug,)
        ).fetchone()["id"]


def test_seed_gir_tre_pizzaer_til_59_kr(tmp_path, monkeypatch):
    db = _oppsett(tmp_path, monkeypatch)
    with db.kobling() as kob:
        rader = list(kob.execute("SELECT * FROM menyelement ORDER BY rekkefolge"))
    assert [r["navn"] for r in rader] == [
        "Margherita",
        "Skinke",
        "Hvit pizza med pære",
    ]
    assert {r["pris_ore"] for r in rader} == {5900}


def test_alle_pizzaer_inneholder_gluten_fra_deigen(tmp_path, monkeypatch):
    """Regresjonsvern: uten deigen som ingrediens ville alle blitt glutenfrie."""
    db = _oppsett(tmp_path, monkeypatch)
    from app import allergener

    with db.kobling() as kob:
        for slug in ("margherita", "skinke", "paere"):
            eid = _meny_id(db, slug)
            koder = {r["kode"] for r in allergener.for_menyelement(kob, eid)}
            assert "gluten" in koder, f"{slug} mangler gluten"
            assert "melk" in koder, f"{slug} mangler melk"


def test_dagsnummer_starter_paa_1_og_okes(tmp_path, monkeypatch):
    db = _oppsett(tmp_path, monkeypatch)
    _tving_apent(db)
    from app.ordrer import Onske, opprett

    eid = _meny_id(db, "margherita")
    a = opprett("Afras", None, [Onske(eid, 1)])
    b = opprett("Kari", None, [Onske(eid, 1)])
    assert a["nummer"] == 1
    assert b["nummer"] == 2


def test_en_etikettjobb_per_pizza_med_teller(tmp_path, monkeypatch):
    db = _oppsett(tmp_path, monkeypatch)
    _tving_apent(db)
    from app.ordrer import Onske, opprett

    res = opprett(
        "Afras",
        None,
        [Onske(_meny_id(db, "margherita"), 2), Onske(_meny_id(db, "paere"), 1)],
    )
    assert res["antall_etiketter"] == 3
    assert res["total_ore"] == 3 * 5900

    with db.kobling() as kob:
        jobber = [
            json.loads(r["nyttelast"])
            for r in kob.execute(
                "SELECT nyttelast FROM jobb WHERE type='etikett' AND ordre_id=? ORDER BY id",
                (res["ordre_id"],),
            )
        ]
    assert [j["tekst"] for j in jobber] == ["Margherita", "Margherita", "Pære"]
    assert [(j["indeks"], j["av"]) for j in jobber] == [(1, 3), (2, 3), (3, 3)]
    assert all(j["nummer"] == res["nummer"] for j in jobber)


def test_utsolgt_avvises(tmp_path, monkeypatch):
    db = _oppsett(tmp_path, monkeypatch)
    _tving_apent(db)
    import pytest

    from app.ordrer import Avvist, Onske, opprett

    eid = _meny_id(db, "paere")
    with db.transaksjon() as kob:
        kob.execute("UPDATE menyelement SET tilgjengelig = 0 WHERE id = ?", (eid,))
    with pytest.raises(Avvist, match="utsolgt"):
        opprett("Afras", None, [Onske(eid, 1)])


def test_stengt_avvises_og_gir_ingen_ordre(tmp_path, monkeypatch):
    db = _oppsett(tmp_path, monkeypatch)
    _tving_apent(db)
    import pytest

    from app.ordrer import Avvist, Onske, opprett

    with db.transaksjon() as kob:
        kob.execute("UPDATE innstilling SET verdi='1' WHERE nokkel='manuelt_stengt'")
    with pytest.raises(Avvist):
        opprett("Afras", None, [Onske(_meny_id(db, "margherita"), 1)])
    with db.kobling() as kob:
        assert kob.execute("SELECT COUNT(*) c FROM ordre").fetchone()["c"] == 0


def test_tom_korg_og_tomt_navn_avvises(tmp_path, monkeypatch):
    db = _oppsett(tmp_path, monkeypatch)
    _tving_apent(db)
    import pytest

    from app.ordrer import Avvist, Onske, opprett

    eid = _meny_id(db, "margherita")
    with pytest.raises(Avvist, match="tom"):
        opprett("Afras", None, [])
    with pytest.raises(Avvist, match="navn"):
        opprett("   ", None, [Onske(eid, 1)])


def test_statusflyt_tillater_lovlig_og_avviser_ulovlig(tmp_path, monkeypatch):
    db = _oppsett(tmp_path, monkeypatch)
    _tving_apent(db)
    import pytest

    from app.ordrer import Avvist, Onske, opprett, sett_status

    res = opprett("Afras", None, [Onske(_meny_id(db, "margherita"), 1)])
    oid = res["ordre_id"]

    assert sett_status(oid, "i_produksjon")["status"] == "i_produksjon"
    assert sett_status(oid, "klar")["status"] == "klar"
    assert sett_status(oid, "levert")["status"] == "levert"

    # Levert er endestasjon.
    with pytest.raises(Avvist):
        sett_status(oid, "klar")


def test_klar_koer_epost_bare_naar_epost_er_oppgitt(tmp_path, monkeypatch):
    db = _oppsett(tmp_path, monkeypatch)
    _tving_apent(db)
    from app.ordrer import Onske, opprett, sett_status

    eid = _meny_id(db, "margherita")
    med = opprett("Med Epost", "a@example.com", [Onske(eid, 1)])
    uten = opprett("Uten Epost", None, [Onske(eid, 1)])

    for oid in (med["ordre_id"], uten["ordre_id"]):
        sett_status(oid, "klar")

    with db.kobling() as kob:
        def maler(ordre_id):
            return [
                json.loads(r["nyttelast"])["mal"]
                for r in kob.execute(
                    "SELECT nyttelast FROM jobb WHERE type='epost' AND ordre_id=? ORDER BY id",
                    (ordre_id,),
                )
            ]
        assert maler(med["ordre_id"]) == ["bestilling_mottatt", "klar_til_henting"]
        assert maler(uten["ordre_id"]) == []


def test_betalt_er_uavhengig_av_status(tmp_path, monkeypatch):
    db = _oppsett(tmp_path, monkeypatch)
    _tving_apent(db)
    from app.ordrer import Onske, opprett, sett_betalt

    res = opprett("Afras", None, [Onske(_meny_id(db, "margherita"), 1)])
    sett_betalt(res["ordre_id"], True)
    with db.kobling() as kob:
        rad = kob.execute(
            "SELECT status, betalt FROM ordre WHERE id = ?", (res["ordre_id"],)
        ).fetchone()
    assert rad["status"] == "ny" and rad["betalt"] == 1


def test_henteskjerm_viser_bare_klare_numre(tmp_path, monkeypatch):
    db = _oppsett(tmp_path, monkeypatch)
    _tving_apent(db)
    from app import ordrer
    from app.ordrer import Onske, opprett, sett_status

    eid = _meny_id(db, "margherita")
    a = opprett("A", None, [Onske(eid, 1)])
    b = opprett("B", None, [Onske(eid, 1)])
    opprett("C", None, [Onske(eid, 1)])

    sett_status(a["ordre_id"], "klar")
    sett_status(b["ordre_id"], "klar")
    sett_status(b["ordre_id"], "levert")

    with db.kobling() as kob:
        assert ordrer.klare_numre(kob) == [a["nummer"]]


def test_snapshot_beskytter_mot_prisendring_underveis(tmp_path, monkeypatch):
    db = _oppsett(tmp_path, monkeypatch)
    _tving_apent(db)
    from app.ordrer import Onske, opprett

    eid = _meny_id(db, "margherita")
    res = opprett("Afras", None, [Onske(eid, 1)])
    with db.transaksjon() as kob:
        kob.execute("UPDATE menyelement SET pris_ore = 9900 WHERE id = ?", (eid,))
    with db.kobling() as kob:
        linje = kob.execute(
            "SELECT * FROM ordrelinje WHERE ordre_id = ?", (res["ordre_id"],)
        ).fetchone()
        ordre = kob.execute(
            "SELECT total_ore FROM ordre WHERE id = ?", (res["ordre_id"],)
        ).fetchone()
    assert linje["pris_ore_snapshot"] == 5900
    assert ordre["total_ore"] == 5900

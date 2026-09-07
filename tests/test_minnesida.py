"""Tester for minnesida — de frosne tallene og at kvitteringene er stengt.

Kjøres med: uv run pytest tests -q
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


def _klient(db):
    """TestClient uten livsløpet: basen er alt klargjort av _oppsett."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.maler import MALKATALOG
    from app.routes import kunde
    from fastapi.staticfiles import StaticFiles

    app = FastAPI()
    app.mount(
        "/static",
        StaticFiles(directory=str(MALKATALOG.parent / "static")),
        name="static",
    )
    app.include_router(kunde.ruter)
    return TestClient(app)


# ── De frosne tallene ────────────────────────────────────────────────────────


def test_tallene_summerer_seg_til_det_samme_tre_veier():
    """299 skal komme ut uansett hvilken vei man legger sammen.

    Dette er hele verdien av testen: skriver noen om en enkelt time eller en
    enkelt rett, faller den her framfor at sida stille viser tall som ikke
    stemmer med hverandre.
    """
    from app import minne

    assert sum(k["pizzaer"] for k in minne.KVELDER) == minne.PIZZAER
    assert sum(n for k in minne.KVELDER for _, n in k["timer"]) == minne.PIZZAER
    assert sum(n for _, _, n in minne.RETTER) == minne.PIZZAER


def test_kronene_er_pizzaer_ganger_prisen():
    from app import minne

    assert minne.KRONER == minne.PIZZAER * 59


def test_topptimen_er_den_hoyeste_timen():
    """Sikrer at ingen søyle kan stikke utenfor ruta: skalaen ER maksimum."""
    from app import minne

    assert minne.TOPPTIME == max(
        n for k in minne.KVELDER for _, n in k["timer"]
    )


def test_minnet_har_ingen_personopplysninger():
    """Ingen navn, ingen e-postadresser — bare summer.

    Basen har 119 adresser og 208 fornavn. Ingenting av det skal kunne snike
    seg inn i modulen som mater en offentlig side.
    """
    from app import minne

    tekst = Path(minne.__file__).read_text()
    assert "@" not in tekst.split('"""')[2], "e-postadresse i minne.py?"


# ── Forsida ──────────────────────────────────────────────────────────────────


def test_stengt_forside_viser_tallene_og_ingen_bestillingsknapp(tmp_path, monkeypatch):
    db = _oppsett(tmp_path, monkeypatch)
    from app import innstillinger, minne

    innstillinger.sett("manuelt_stengt", "1")
    svar = _klient(db).get("/")
    assert svar.status_code == 200
    kropp = svar.text

    # Tallene skal staa der.
    assert str(minne.PIZZAER) in kropp
    assert "Helga i tall" in kropp
    assert "Menyen vi hadde" in kropp
    # Bestillingsveien skal vaere borte.
    assert 'name="kundenavn"' not in kropp
    assert "Send bestilling" not in kropp
    # Det gamle raude «midlertidig stengt»-varselet hoerer ikke til her.
    assert "midlertidig stengt" not in kropp


def test_aapen_forside_er_urort(tmp_path, monkeypatch):
    """Bestillingsveien skal vaere noyaktig som foer naar det er aapent."""
    db = _oppsett(tmp_path, monkeypatch)
    svar = _klient(db).get("/")
    assert svar.status_code == 200
    kropp = svar.text
    assert 'name="kundenavn"' in kropp
    assert "Send bestilling" in kropp
    # Minnesida skal ikke vises midt i en service.
    assert "Helga i tall" not in kropp
    assert "Hvordan det virket" not in kropp


# ── Kvitteringene ────────────────────────────────────────────────────────────


def _legg_inn_ordre(db):
    from app import ordrer

    with db.kobling() as kob:
        mid = kob.execute(
            "SELECT id FROM menyelement WHERE slug = 'skinke'"
        ).fetchone()["id"]
    return ordrer.opprett("Testesen", "", [ordrer.Onske(mid, 1)])


def test_kvittering_virker_naar_det_er_aapent(tmp_path, monkeypatch):
    db = _oppsett(tmp_path, monkeypatch)
    res = _legg_inn_ordre(db)
    svar = _klient(db).get(f"/kvittering/{res['ordre_id']}")
    assert svar.status_code == 200
    assert "Testesen" in svar.text


def test_kvittering_er_stengt_naar_sida_er_stengt(tmp_path, monkeypatch):
    """Det er dette som slaar av de 208 gjettbare adressene."""
    db = _oppsett(tmp_path, monkeypatch)
    res = _legg_inn_ordre(db)
    from app import innstillinger

    innstillinger.sett("manuelt_stengt", "1")

    svar = _klient(db).get(f"/kvittering/{res['ordre_id']}")
    assert svar.status_code == 404
    assert "Testesen" not in svar.text


def test_status_lekker_ingenting_naar_sida_er_stengt(tmp_path, monkeypatch):
    db = _oppsett(tmp_path, monkeypatch)
    res = _legg_inn_ordre(db)
    from app import innstillinger

    klient = _klient(db)
    assert klient.get(f"/status/{res['ordre_id']}").json()["finnes"] is True

    innstillinger.sett("manuelt_stengt", "1")
    svar = klient.get(f"/status/{res['ordre_id']}").json()
    assert svar == {"finnes": False}

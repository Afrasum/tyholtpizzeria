"""Tester for minnesida — de frosne tallene og at kvitteringene er stengt.

Kjøres med: uv run pytest tests -q
"""

from __future__ import annotations

import re
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


def test_overskriftene_viser_300_men_regnestykkene_bruker_299():
    """De to tallene maa ikke bytte plass.

    «300+» er sant og staar i overskriftene. Prosentene per rett summerer seg
    til 100 bare mot det LOGGEDE tallet, saa alt som regnes maa bruke det.
    """
    from app import minne

    assert minne.PIZZAER_VIST == "300+"
    assert minne.PIZZAER_MINST > minne.PIZZAER
    assert minne.KRONER == minne.PIZZAER * 59
    assert sum(n for _, _, n in minne.RETTER) == minne.PIZZAER


def test_sida_viser_300_i_toppen_og_forklarer_avviket(tmp_path, monkeypatch):
    db = _oppsett(tmp_path, monkeypatch)
    from app import innstillinger, minne

    innstillinger.sett("manuelt_stengt", "1")
    klient = _klient(db)

    forside = klient.get("/").text
    assert minne.PIZZAER_VIST in forside
    # Det loggede tallet skal ikke staa som en overskrift paa forsida.
    assert f"<b>{minne.PIZZAER}</b>" not in forside

    helga = klient.get("/helga").text
    assert minne.PIZZAER_VIST in helga
    # Avviket maa forklares der tallene faktisk brytes ned.
    assert str(minne.PIZZAER_MINST) in helga
    assert str(minne.PIZZAER) in helga


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
    # Regex over hele fila framfor aa splitte paa docstringen: en indeks inn i
    # docstringen brekker — eller blir stille sann — neste gang noen skriver om
    # kommentaren oeverst.
    adresser = re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", tekst)
    assert not adresser, f"e-postadresse i minne.py: {adresser}"
    # Fornavna fra basen har ingenting aa gjore her heller. Modulen skal
    # inneholde tall, ikke rader.
    assert "kundenavn" not in tekst


# ── Forsida ──────────────────────────────────────────────────────────────────


def test_stengt_forside_er_nettsida_og_ikke_skjemaet(tmp_path, monkeypatch):
    """Stengt «/» skal rendre hjem.html, ikke bestillingsmalen.

    De to malene er helt ulike sider. Denne testen er det som fanger at ruta
    plukker feil av dem.
    """
    db = _oppsett(tmp_path, monkeypatch)
    from app import innstillinger, minne

    innstillinger.sett("manuelt_stengt", "1")
    svar = _klient(db).get("/")
    assert svar.status_code == 200
    kropp = svar.text

    assert str(minne.PIZZAER) in kropp
    assert "Helga i tall" in kropp
    assert "Menyen vi hadde" in kropp
    assert "Hvordan det virket" in kropp
    assert 'href="/helga"' in kropp
    # Catering er grunnen til at sida finnes mens vi er stengt. Den skal
    # staa allerede i heroen og ha en egen vei ned til kontaktbolken.
    assert "cateringoppdrag" in kropp
    assert 'href="#ta-kontakt"' in kropp
    assert "subject=Catering" in kropp
    # Bestillingsveien skal ikke finnes i det hele tatt.
    assert 'name="kundenavn"' not in kropp
    assert "Send bestilling" not in kropp
    assert 'action="/bestill"' not in kropp
    # Det roede «midlertidig stengt»-varselet hoerer til en pause under
    # service, ikke til en nettside.
    assert "midlertidig stengt" not in kropp


def test_aapen_forside_er_bestillingsskjemaet_urort(tmp_path, monkeypatch):
    """Aapen «/» skal vaere forside.html, noeyaktig som foer."""
    db = _oppsett(tmp_path, monkeypatch)
    svar = _klient(db).get("/")
    assert svar.status_code == 200
    kropp = svar.text
    assert 'name="kundenavn"' in kropp
    assert "Send bestilling" in kropp
    assert 'id="kurv"' in kropp
    # Nettsida skal ikke blande seg inn i en service.
    assert "Hvordan det virket" not in kropp
    assert "Menyen vi hadde" not in kropp


def test_helga_er_naabar_i_begge_tilstander(tmp_path, monkeypatch):
    """Tallsida er permanent. Den skal ikke forsvinne fordi vi aapner igjen."""
    db = _oppsett(tmp_path, monkeypatch)
    from app import innstillinger, minne

    klient = _klient(db)
    for stengt in ("0", "1"):
        innstillinger.sett("manuelt_stengt", stengt)
        svar = klient.get("/helga")
        assert svar.status_code == 200, stengt
        assert "Da det sto på" in svar.text
        assert str(minne.TOPPTIME) in svar.text


def test_helga_viser_hver_time_fra_begge_kveldene(tmp_path, monkeypatch):
    """Grafen skal ha en soyle per time, med hoyde satt i rem.

    Prosenthoyder inne i et spor som maaler seg etter innholdet er sirkulaere,
    og da kollapset nettopp den hoyeste soyla. Testen holder rem-formen fast.
    """
    db = _oppsett(tmp_path, monkeypatch)
    from app import minne

    kropp = _klient(db).get("/helga").text
    antall_soyler = kropp.count('class="n-soyle"')
    assert antall_soyler == sum(len(k["timer"]) for k in minne.KVELDER)
    assert "rem" in kropp.split('class="n-soyle" style="height: ')[1][:12]
    # Topptimen skal vaere merket, og bare den.
    assert kropp.count('class="hoyest"') == 1


def test_ingen_plassholdertekst_paa_den_offentlige_sida(tmp_path, monkeypatch):
    """En «ikke skrevet ennå»-rute skal ikke kunne bli staaende ute.

    Teksten om oss er data (minne.OM_OSS), ikke en plassholder i malen. Er den
    tom, hopper malen over avsnittene framfor aa vise en tom ramme.
    """
    db = _oppsett(tmp_path, monkeypatch)
    from app import innstillinger

    innstillinger.sett("manuelt_stengt", "1")
    kropp = _klient(db).get("/").text
    for lekkasje in ("ikke skrevet", "Her skal det staa", "Her skal det stå",
                     "FYLL INN", "TODO", "Lorem"):
        assert lekkasje not in kropp, lekkasje
    # Seksjonen skal likevel finnes, med den ene linja vi kan staa for.
    assert "Hvem vi er" in kropp
    assert "enklere å ha én pris enn tre" in kropp


def test_om_oss_avsnitt_havner_paa_sida(tmp_path, monkeypatch):
    """Naar teksten er skrevet skal den faktisk vises."""
    db = _oppsett(tmp_path, monkeypatch)
    from app import innstillinger, minne

    innstillinger.sett("manuelt_stengt", "1")
    monkeypatch.setattr(minne, "OM_OSS", ("Vi er to brodre.", "Vi liker deig."))
    kropp = _klient(db).get("/").text
    assert "Vi er to brodre." in kropp
    assert "Vi liker deig." in kropp


def test_instagram_lenka_er_rein(tmp_path, monkeypatch):
    """URL-en bygges av brukernavnet, ikke limt inn fra en delingslenke.

    Instagrams «del»-knapp gir en URL med utm_source og en `stkn`-token som
    hoerer til den som delte. Den skal aldri ut paa en offentlig side.
    """
    db = _oppsett(tmp_path, monkeypatch)
    from app import innstillinger

    klient = _klient(db)
    innstillinger.sett("manuelt_stengt", "1")
    for sti in ("/", "/helga"):
        kropp = klient.get(sti).text
        assert "https://www.instagram.com/tyholt_pizzeria/" in kropp, sti
        assert "utm_source" not in kropp, sti
        assert "stkn=" not in kropp, sti
    # Ogsaa paa bestillingssida.
    innstillinger.sett("manuelt_stengt", "0")
    kropp = klient.get("/").text
    assert "instagram.com/tyholt_pizzeria/" in kropp
    assert "stkn=" not in kropp


def test_uten_instagram_forsvinner_lenkene_heilt(tmp_path, monkeypatch):
    """Tom innstilling skal fjerne lenkene, ikke gi en lenke til ingenting."""
    db = _oppsett(tmp_path, monkeypatch)
    from app import innstillinger

    innstillinger.sett("instagram", "")
    innstillinger.sett("manuelt_stengt", "1")
    kropp = _klient(db).get("/").text
    assert "instagram.com" not in kropp
    assert "Følg oss" not in kropp


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

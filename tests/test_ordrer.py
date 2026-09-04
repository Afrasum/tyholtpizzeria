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


def test_dagsnummer_okes_med_en(tmp_path, monkeypatch):
    """Startnummeret er tilfeldig, men stigningen skal vaere nøyaktig en."""
    db = _oppsett(tmp_path, monkeypatch)
    _tving_apent(db)
    from app.ordrer import Onske, opprett

    eid = _meny_id(db, "margherita")
    a = opprett("Afras", None, [Onske(eid, 1)])
    b = opprett("Kari", None, [Onske(eid, 1)])
    assert b["nummer"] == a["nummer"] + 1


def test_en_etikett_per_pizza_i_en_strimmeljobb(tmp_path, monkeypatch):
    """Én jobb per ordre, men én etikett per pizza inne i den.

    Strimmelen finnes for tapens skyld: printeren mater ut 2,5 cm per jobb,
    så alle etikettene i en ordre printes sammenhengende.
    """
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
        rader = list(
            kob.execute(
                "SELECT nyttelast FROM jobb WHERE type='etikett' AND ordre_id=? ORDER BY id",
                (res["ordre_id"],),
            )
        )
    assert len(rader) == 1, "skal vaere EN jobb for hele ordren"
    last = json.loads(rader[0]["nyttelast"])
    ets = last["etiketter"]

    assert [e["tekst"] for e in ets] == ["Margherita", "Margherita", "Pære"]
    assert [(e["indeks"], e["av"]) for e in ets] == [(1, 3), (2, 3), (3, 3)]
    assert last["nummer"] == res["nummer"]
    assert last["kundenavn"] == "Afras"


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

    # Levert er ikke lenger endestasjon: ett trinn tilbake er angreknappen for
    # et feiltrykk i koen. Men bare ett trinn — den kan ikke settes tilbake til
    # «ny», for da ville nummeret vaert i produksjon uten at noen hadde bestilt.
    assert sett_status(oid, "klar")["status"] == "klar"
    assert sett_status(oid, "levert")["status"] == "levert"
    with pytest.raises(Avvist):
        sett_status(oid, "ny")

    # Og en tilstand som ikke finnes skal fortsatt avvises.
    with pytest.raises(Avvist):
        sett_status(oid, "pizzaen_brant")


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


def test_maks_10_pizzaer_per_bestilling(tmp_path, monkeypatch):
    db = _oppsett(tmp_path, monkeypatch)
    _tving_apent(db)
    import pytest

    from app.ordrer import Avvist, Onske, opprett

    eid = _meny_id(db, "margherita")
    assert opprett("Afras", None, [Onske(eid, 10)])["antall_etiketter"] == 10
    with pytest.raises(Avvist, match="Maks 10"):
        opprett("Afras", None, [Onske(eid, 11)])


def test_forlatt_kan_settes_manuelt_og_angres(tmp_path, monkeypatch):
    db = _oppsett(tmp_path, monkeypatch)
    _tving_apent(db)
    from app.ordrer import Onske, opprett, sett_status

    res = opprett("Afras", None, [Onske(_meny_id(db, "margherita"), 1)])
    oid = res["ordre_id"]
    sett_status(oid, "klar")
    assert sett_status(oid, "forlatt")["status"] == "forlatt"
    # Kunden dukket opp likevel.
    assert sett_status(oid, "levert")["status"] == "levert"


def test_forlatt_fjerner_nummeret_fra_henteskjermen(tmp_path, monkeypatch):
    db = _oppsett(tmp_path, monkeypatch)
    _tving_apent(db)
    from app import ordrer
    from app.ordrer import Onske, opprett, sett_status

    res = opprett("Afras", None, [Onske(_meny_id(db, "margherita"), 1)])
    sett_status(res["ordre_id"], "klar")
    with db.kobling() as kob:
        assert ordrer.klare_numre(kob) == [res["nummer"]]
    sett_status(res["ordre_id"], "forlatt")
    with db.kobling() as kob:
        assert ordrer.klare_numre(kob) == []


def test_nummeret_er_delt_paa_tvers_av_pizzatyper(tmp_path, monkeypatch):
    """Én teller for alle typer, og samme nummer på alle pizzaer i en ordre.

    Dagens første pærepizza skal IKKE begynne på 1 — den arver ordrenummeret,
    som er én mer enn forrige bestilling uansett hva den inneholdt.
    """
    db = _oppsett(tmp_path, monkeypatch)
    _tving_apent(db)
    from app.ordrer import Onske, opprett

    m = _meny_id(db, "margherita")
    s = _meny_id(db, "skinke")
    p = _meny_id(db, "paere")

    en = opprett("A", None, [Onske(m, 1)])                       # bare margherita
    to = opprett("B", None, [Onske(s, 2)])                       # bare skinke
    tre = opprett("C", None, [Onske(p, 1), Onske(m, 1)])         # forste paere + margherita

    assert [to["nummer"], tre["nummer"]] == [en["nummer"] + 1, en["nummer"] + 2], (
        "telleren skal ga pa ordre, ikke per pizzatype"
    )

    # Ordre 3 har to ulike pizzaer — begge etikettene skal si 3.
    with db.kobling() as kob:
        last = json.loads(
            kob.execute(
                "SELECT nyttelast FROM jobb WHERE type='etikett' AND ordre_id=?",
                (tre["ordre_id"],),
            ).fetchone()["nyttelast"]
        )
    assert last["nummer"] == tre["nummer"], "samme ordre ma ha samme nummer"
    assert sorted(e["tekst"] for e in last["etiketter"]) == ["Margherita", "Pære"]
    assert sorted((e["indeks"], e["av"]) for e in last["etiketter"]) == [(1, 2), (2, 2)]


def test_slett_alt_tommer_basen_og_stiller_telleren_tilbake(tmp_path, monkeypatch):
    """«Slett databasen» skal ikke etterlate loese linjer eller jobber."""
    db = _oppsett(tmp_path, monkeypatch)
    _tving_apent(db)
    from app import ordrer
    from app.ordrer import Onske, opprett

    eid = _meny_id(db, "margherita")
    for _ in range(3):
        opprett("Tester", "a@example.com", [Onske(eid, 2)])

    with db.kobling() as kob:
        dag = ordrer.gjeldende_salgsdag(kob)
        assert kob.execute("SELECT COUNT(*) c FROM ordrelinje").fetchone()["c"] == 3
        assert kob.execute("SELECT COUNT(*) c FROM jobb").fetchone()["c"] == 6

    assert ordrer.slett_alt() == 3

    with db.kobling() as kob:
        for tabell in ("ordre", "ordrelinje", "jobb", "statuslogg"):
            n = kob.execute(f"SELECT COUNT(*) c FROM {tabell}").fetchone()["c"]
            assert n == 0, f"{tabell} hadde {n} rader igjen"

    # Telleren begynner forfra fra dagens startnummer.
    with db.kobling() as kob:
        start = kob.execute(
            "SELECT startnummer FROM salgsdag WHERE id = ?", (dag["id"],)
        ).fetchone()["startnummer"]
    assert opprett("Etter", None, [Onske(eid, 1)])["nummer"] == start


def test_kodebokstaven_paa_menyen_matcher_etiketten(tmp_path, monkeypatch):
    """Bokstaven kunden ser MA vaere den som printes pa esken.

    «Hvit pizza med pære» heter P pa etiketten. Utledet fra rettens navn ville
    den blitt H, og da stemmer ikke systemet kunden ser med systemet kjokkenet
    leser.
    """
    db = _oppsett(tmp_path, monkeypatch)
    from app import meny

    with db.kobling() as kob:
        koder = {r["navn"]: r["kode"] for r in meny.full_meny(kob)}
    assert koder == {"Margherita": "M", "Skinke": "S", "Hvit pizza med pære": "P"}


def test_vipps_lenken_utledes_riktig_fra_nummeret(tmp_path, monkeypatch):
    """Verifisert mot de seks ekte lenkene vi fikk oppgitt."""
    _oppsett(tmp_path, monkeypatch)
    from app.innstillinger import vipps_url

    fasit = {
        "40166715": "https://qr.vipps.no/28/2/01/031/4740166715?v=1",
        "93604144": "https://qr.vipps.no/28/2/01/031/4793604144?v=1",
        "90214070": "https://qr.vipps.no/28/2/01/031/4790214070?v=1",
        "95369058": "https://qr.vipps.no/28/2/01/031/4795369058?v=1",
        "90831803": "https://qr.vipps.no/28/2/01/031/4790831803?v=1",
        "41783544": "https://qr.vipps.no/28/2/01/031/4741783544?v=1",
    }
    for nummer, forventet in fasit.items():
        assert vipps_url(nummer) == forventet, nummer

    # Toleranse for hvordan folk skriver nummeret.
    assert vipps_url("401 66 715") == fasit["40166715"]
    assert vipps_url("+4740166715") == fasit["40166715"]
    assert vipps_url("4740166715") == fasit["40166715"]

    # Soppel skal gi tom streng, ikke en lenke til feil person.
    assert vipps_url("123") == ""
    assert vipps_url("") == ""


def test_bytte_av_mottaker_slaar_gjennom(tmp_path, monkeypatch):
    db = _oppsett(tmp_path, monkeypatch)
    from app import innstillinger

    with db.kobling() as kob:
        liste = innstillinger.mottakere(kob)
    assert [m["navn"] for m in liste] == [
        "Afras", "Torkil", "Kristian", "Andreas", "Tobias", "Morten"
    ]

    # Uten valg: forste i lista, sa kvitteringen aldri staar tom.
    with db.kobling() as kob:
        assert innstillinger.aktiv_mottaker(kob)["navn"] == "Afras"

    kristian = next(m for m in liste if m["navn"] == "Kristian")
    innstillinger.sett("vipps_mottaker_id", str(kristian["id"]))

    with db.kobling() as kob:
        alle = innstillinger.alle(kob)
    assert alle["vipps_navn"] == "Kristian"
    assert alle["vipps_nummer"] == "90214070"
    assert alle["vipps_url"] == "https://qr.vipps.no/28/2/01/031/4790214070?v=1"


def test_skjermen_viser_nye_ordrer_som_under_arbeid(tmp_path, monkeypatch):
    """Nummeret skal opp pa tavla i det sekundet bestillingen er inne.

    Kunden som nettopp bestilte skal ikke sta og lure pa om den gikk gjennom
    fordi kjokkenet ikke har trykket «i produksjon» ennaa.
    """
    db = _oppsett(tmp_path, monkeypatch)
    _tving_apent(db)
    from app.routes.skjerm import _tall
    from app.ordrer import Onske, opprett, sett_status

    eid = _meny_id(db, "margherita")
    a = opprett("A", None, [Onske(eid, 1)])     # ny
    b = opprett("B", None, [Onske(eid, 1)])     # -> i produksjon
    c = opprett("C", None, [Onske(eid, 1)])     # -> klar
    d = opprett("D", None, [Onske(eid, 1)])     # -> levert

    sett_status(b["ordre_id"], "i_produksjon")
    sett_status(c["ordre_id"], "klar")
    sett_status(d["ordre_id"], "klar")
    sett_status(d["ordre_id"], "levert")

    with db.kobling() as kob:
        tall = _tall(kob)

    assert tall["under_arbeid"] == [a["nummer"], b["nummer"]], (
        "bade ny og i_produksjon skal sta under arbeid"
    )
    assert tall["klare"] == [c["nummer"]]
    assert d["nummer"] not in tall["under_arbeid"] + tall["klare"]


def test_skjul_ordre_tar_den_ut_av_flatene_men_beholder_raden(tmp_path, monkeypatch):
    db = _oppsett(tmp_path, monkeypatch)
    _tving_apent(db)
    from app import ordrer
    from app.ordrer import Onske, opprett, skjul_ordre

    eid = _meny_id(db, "margherita")
    feil = opprett("Feiltrykk", "a@example.com", [Onske(eid, 2)])
    ekte = opprett("Ekte", None, [Onske(eid, 1)])
    ordrer.sett_status(feil["ordre_id"], "i_produksjon")
    ordrer.sett_status(feil["ordre_id"], "klar")
    ordrer.sett_status(ekte["ordre_id"], "i_produksjon")
    ordrer.sett_status(ekte["ordre_id"], "klar")

    with db.kobling() as kob:
        assert len(ordrer.for_admin(kob)) == 2
        assert feil["nummer"] in ordrer.klare_numre(kob)

    assert skjul_ordre(feil["ordre_id"]) is True

    # Borte fra arbeidsflatene ...
    with db.kobling() as kob:
        synlige = [r["ordre"]["dagsnummer"] for r in ordrer.for_admin(kob)]
        assert synlige == [ekte["nummer"]]
        assert feil["nummer"] not in ordrer.klare_numre(kob)

        # ... men raden og alt som henger ved den staar igjen.
        rad = kob.execute(
            "SELECT skjult FROM ordre WHERE id = ?", (feil["ordre_id"],)
        ).fetchone()
        assert rad is not None and rad["skjult"] == 1
        assert kob.execute(
            "SELECT count(*) c FROM ordrelinje WHERE ordre_id = ?", (feil["ordre_id"],)
        ).fetchone()["c"] == 1

    # Angrbar.
    assert skjul_ordre(feil["ordre_id"], skjult=False) is True
    with db.kobling() as kob:
        assert len(ordrer.for_admin(kob)) == 2

    # Nummeret gjenbrukes aldri, skjult eller ei.
    skjul_ordre(feil["ordre_id"])
    neste = opprett("Etterpaa", None, [Onske(eid, 1)])
    assert neste["nummer"] == ekte["nummer"] + 1


def test_skjult_ordre_stopper_koen_og_slutter_a_mase(tmp_path, monkeypatch):
    """En fjernet ordre skal ikke printes, og ikke staa igjen i feilbanneret."""
    db = _oppsett(tmp_path, monkeypatch)
    _tving_apent(db)
    from app import jobber
    from app.ordrer import Onske, opprett, skjul_ordre

    eid = _meny_id(db, "margherita")
    ordre = opprett("Feiltrykk", None, [Onske(eid, 1)])
    oid = ordre["ordre_id"]

    def jobbstatus():
        with db.kobling() as kob:
            return [
                r["status"]
                for r in kob.execute(
                    "SELECT status FROM jobb WHERE ordre_id = ? AND type = 'etikett'",
                    (oid,),
                )
            ]

    assert "ny" in jobbstatus(), "etikettjobben skal ligge i koen for vi skjuler"

    skjul_ordre(oid)

    # Ingen jobb igjen som en arbeider kan plukke opp.
    assert "ny" not in jobbstatus()
    # ... og den staar ikke i feilbanneret i admin, selv om den er merket feilet.
    assert all(j["ordre_id"] != oid for j in jobber.feilede())


def test_slett_ordre_fjerner_raden_men_frigir_ikke_nummeret(tmp_path, monkeypatch):
    """Soppelboetta i admin: raden skal vaere borte, nummeret skal ikke gaa igjen.

    To esker i samme rom med samme tall er den ene feilen dette systemet
    aldri skal kunne gjore, sa selv en permanent sletting lar telleren staa.
    """
    db = _oppsett(tmp_path, monkeypatch)
    _tving_apent(db)
    from app import ordrer
    from app.ordrer import Onske, opprett, slett_ordre

    eid = _meny_id(db, "margherita")
    feil = opprett("Feiltrykk", "a@example.com", [Onske(eid, 2)])
    ekte = opprett("Ekte", None, [Onske(eid, 1)])

    with db.kobling() as kob:
        assert len(ordrer.for_admin(kob)) == 2

    assert slett_ordre(feil["ordre_id"]) is True
    assert slett_ordre(feil["ordre_id"]) is False, "andre sletting finner ingenting"

    with db.kobling() as kob:
        synlige = [r["ordre"]["dagsnummer"] for r in ordrer.for_admin(kob)]
        assert synlige == [ekte["nummer"]]

        # Linjer, statuslogg og jobber folger med via ON DELETE CASCADE.
        for tabell in ("ordrelinje", "statuslogg", "jobb"):
            n = kob.execute(
                f"SELECT COUNT(*) AS n FROM {tabell} WHERE ordre_id = ?",
                (feil["ordre_id"],),
            ).fetchone()["n"]
            assert n == 0, f"{tabell} skulle vaert tomt for den slettede ordren"

    neste = opprett("Neste", None, [Onske(eid, 1)])
    assert neste["nummer"] > ekte["nummer"], "nummeret til en slettet ordre er brent"


def test_solgte_pizzaer_teller_skjulte_men_ikke_avbrutte(tmp_path, monkeypatch):
    """Salgstallet skal ikke telle nedover naar leverte ordrer ryddes vekk."""
    db = _oppsett(tmp_path, monkeypatch)
    _tving_apent(db)
    from app import ordrer
    from app.ordrer import Onske, opprett

    eid = _meny_id(db, "margherita")
    a = opprett("A", None, [Onske(eid, 2)])
    b = opprett("B", None, [Onske(eid, 3)])
    c = opprett("C", None, [Onske(eid, 4)])

    with db.kobling() as kob:
        assert ordrer.solgte_pizzaer(kob) == 9

    # Skjult teller fortsatt med — pizzaen er laget og betalt.
    ordrer.skjul_ordre(a["ordre_id"])
    with db.kobling() as kob:
        assert ordrer.solgte_pizzaer(kob) == 9
        assert len(ordrer.for_admin(kob)) == 2
        assert [r["ordre"]["id"] for r in ordrer.skjulte_for_admin(kob)] == [
            a["ordre_id"]
        ]

    # Avbrutt teller ikke — den ble aldri laget.
    ordrer.sett_status(b["ordre_id"], "avbrutt")
    with db.kobling() as kob:
        assert ordrer.solgte_pizzaer(kob) == 6

    # Slettet teller ikke — raden finnes ikke lenger.
    ordrer.slett_ordre(c["ordre_id"])
    with db.kobling() as kob:
        assert ordrer.solgte_pizzaer(kob) == 2


def test_for_admin_gir_eldste_ordre_forst(tmp_path, monkeypatch):
    """Nye ordrer skal legge seg nederst, ikke skyve radene under fingeren."""
    db = _oppsett(tmp_path, monkeypatch)
    _tving_apent(db)
    from app import ordrer
    from app.ordrer import Onske, opprett

    eid = _meny_id(db, "margherita")
    numre = [opprett(n, None, [Onske(eid, 1)])["nummer"] for n in ("A", "B", "C")]

    with db.kobling() as kob:
        assert [r["ordre"]["dagsnummer"] for r in ordrer.for_admin(kob)] == numre


def test_nullstill_dagen_tommer_lista_uten_a_slette_noe(tmp_path, monkeypatch):
    """Den andre knappen: blank flate, men alt ligger der og kan hentes tilbake."""
    db = _oppsett(tmp_path, monkeypatch)
    _tving_apent(db)
    from app import jobber, ordrer
    from app.ordrer import Onske, opprett

    eid = _meny_id(db, "margherita")
    for navn in ("A", "B", "C"):
        opprett(navn, None, [Onske(eid, 1)])
    sist = opprett("Siste", None, [Onske(eid, 1)])
    ordrer.sett_status(sist["ordre_id"], "i_produksjon")
    ordrer.sett_status(sist["ordre_id"], "klar")

    with db.kobling() as kob:
        dag = ordrer.gjeldende_salgsdag(kob)
        assert len(ordrer.for_admin(kob)) == 4
        assert ordrer.klare_numre(kob) == [sist["nummer"]]

    assert ordrer.skjul_alle(dag["id"]) == 4
    assert ordrer.skjul_alle(dag["id"]) == 0, "andre trykk finner ingenting igjen"

    with db.kobling() as kob:
        # Blank flate ...
        assert ordrer.for_admin(kob) == []
        assert ordrer.klare_numre(kob) == []
        # ... men ingenting er borte.
        assert kob.execute("SELECT COUNT(*) c FROM ordre").fetchone()["c"] == 4
        assert kob.execute("SELECT COUNT(*) c FROM ordrelinje").fetchone()["c"] == 4
        assert len(ordrer.skjulte_for_admin(kob)) == 4
        assert ordrer.solgte_pizzaer(kob) == 4, "salgstallet staar"

    # Ingen etikett skal komme ut av en ordre som nettopp ble ryddet vekk ...
    with db.kobling() as kob:
        ventende = kob.execute(
            "SELECT COUNT(*) c FROM jobb WHERE status = 'ny'"
        ).fetchone()["c"]
    assert ventende == 0, "koen skulle vaert toemt"
    # ... og den skal heller ikke mase i feilbanneret etterpa.
    assert jobber.feilede() == []

    # Og en enkelt kan hentes tilbake.
    ordrer.skjul_ordre(sist["ordre_id"], skjult=False)
    with db.kobling() as kob:
        assert [r["ordre"]["dagsnummer"] for r in ordrer.for_admin(kob)] == [
            sist["nummer"]
        ]
        assert ordrer.klare_numre(kob) == [sist["nummer"]]

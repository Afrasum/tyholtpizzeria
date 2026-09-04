"""Rendrer etiketten som PNG.

Geometrien er printerens, ikke vår: PT-P300BT trykker 64 px av 12 mm tape ved
180 dpi. Vi lager et 88 px høyt bilde og holder alt innhold i de midterste
64 pikslene — de øverste og nederste 12 blir ikke trykket. Bredden er fri og
blir tapelengden.

labelmaker.read_png() inverterer, roterer -90, speiler og padder til 128 px
før den sendes, så vi tegner rett fram: svart tekst på hvit bakgrunn.

Merk: printlabel.py sitt -i/--image er dødt i commit 27bb7bc — flagget finnes
i hjelpeteksten, men args.image brukes bare til å hoppe over render-blokken,
og da ryker «assert data is not None». Vi bruker labelmaker.py, som faktisk
kaller read_png().
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HOYDE = 88          # px, hele bildet
TRYKK_TOPP = 12     # px, første trykkbare rad
TRYKK_HOYDE = 64    # px, trykkflate
MARG = 8            # px, luft i hver ende av tapen

# Forkortelser sparer plass: «M» framfor «Margherita» frigjør et helt ord.
# Settes per menyelement i basen; dette er bare fallback.
FORKORTELSER = {"margherita": "M", "skinke": "S", "paere": "P"}

# Fet skrift er ikke pynt her — tynne streker forsvinner i binariseringen.
FONTKANDIDATER = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",       # Debian/rpi5
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",          # macOS
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/HelveticaNeue.ttc",
)


def finn_font(storrelse: int) -> ImageFont.FreeTypeFont:
    for sti in FONTKANDIDATER:
        if Path(sti).exists():
            return ImageFont.truetype(sti, storrelse)
    return ImageFont.load_default(storrelse)


def _mal(tegner: ImageDraw.ImageDraw, tekst: str, font) -> tuple[int, int]:
    v, o, h, n = tegner.textbbox((0, 0), tekst, font=font)
    return h - v, n - o


def _qr_bilde(nyttelast: str, side: int) -> Image.Image | None:
    """QR som passer i trykkflaten, eller None hvis segno mangler.

    Med 64 px å gå på blir modulene små. Version 2 (25x25) gir ~2,5 px per
    modul, altså 0,36 mm — på grensen av hva et telefonkamera klarer fra
    termotape. Derfor er QR av som standard til vi har skannet en ekte en.
    """
    try:
        import segno
    except ImportError:
        return None
    qr = segno.make(nyttelast, error="l")
    matrise = [list(rad) for rad in qr.matrix]
    n = len(matrise)
    ramme = 1
    rutenett = Image.new("L", (n + 2 * ramme, n + 2 * ramme), 255)
    for y, rad in enumerate(matrise):
        for x, verdi in enumerate(rad):
            if verdi:
                rutenett.putpixel((x + ramme, y + ramme), 0)
    # NEAREST framfor interpolering: en QR-modul skal bli en skarp firkant,
    # ikke en grå overgang som binariseringen gjetter på.
    return rutenett.resize((side, side), Image.NEAREST)


KLIPPEROM = 26      # px mellom etiketter i en strimmel (~4 mm), med klippeguide


def _mal_etikett(
    tekst: str,
    nummer: int,
    kundenavn: str = "",
    indeks: int = 1,
    av: int = 1,
    forkortelse: str | None = None,
    qr_url: str | None = None,
) -> Image.Image:
    """Tegn én etikett som eget bilde, 88 px høyt og akkurat så bredt som nødvendig."""
    return _tegn(
        tekst=tekst, nummer=nummer, kundenavn=kundenavn, indeks=indeks, av=av,
        forkortelse=forkortelse, qr_url=qr_url,
    )


def render_strimmel(
    sti: Path,
    etiketter: list[dict],
    qr_url: str | None = None,
) -> Path:
    """Sy flere etiketter sammen til én strimmel med klippeguider.

    Dette er tapesparingen. Printeren mater ut 2,5 cm før hver utskrift —
    avstanden fra skrivehodet til utgangen — og de kan ikke gjenbrukes. Ved å
    sende alle etikettene i en ordre som ÉN utskrift betaler vi forspillet én
    gang i stedet for én gang per pizza.

    Det koster ingen ekstra klipp: P300BT har ingen autokutter, så etikettene
    klippes for hånd uansett. Nå klippes det mellom dem framfor etter hver.
    """
    if not etiketter:
        raise ValueError("ingen etiketter å printe")

    from . import config

    biter = [
        _tegn(
            tekst=e["tekst"],
            nummer=e["nummer"],
            kundenavn=e.get("kundenavn", ""),
            indeks=e.get("indeks", 1),
            av=e.get("av", 1),
            forkortelse=e.get("forkortelse"),
            # Med QR_BARE_FORSTE far bare den forste etiketten i ordren QR.
            qr_url=qr_url if (i == 0 or not config.QR_BARE_FORSTE) else None,
        )
        for i, e in enumerate(etiketter)
    ]

    # Blank hale sa siste etikett kommer helt ut av maskinen for vi klipper.
    # Se config.PRINT_HALE for hvorfor dette ligger i bildet og ikke i
    # margin-kommandoen.
    bredde = (
        sum(b.width for b in biter)
        + KLIPPEROM * (len(biter) - 1)
        + config.PRINT_HALE
    )
    strimmel = Image.new("L", (bredde, HOYDE), 255)
    tegner = ImageDraw.Draw(strimmel)

    x = 0
    for i, bit in enumerate(biter):
        strimmel.paste(bit, (x, 0))
        x += bit.width
        if i < len(biter) - 1:
            # Stiplet klippeguide midt i mellomrommet.
            guide = x + KLIPPEROM // 2
            for y in range(TRYKK_TOPP, TRYKK_TOPP + TRYKK_HOYDE, 6):
                tegner.line((guide, y, guide, y + 3), fill=0, width=1)
            x += KLIPPEROM

    sti.parent.mkdir(parents=True, exist_ok=True)
    strimmel.save(sti)
    return sti


def render(
    sti: Path,
    tekst: str,
    nummer: int,
    kundenavn: str = "",
    indeks: int = 1,
    av: int = 1,
    forkortelse: str | None = None,
    qr_url: str | None = None,
) -> Path:
    """Én etikett til fil. Beholdt for prøveutskrift og tester."""
    bilde = _tegn(
        tekst=tekst, nummer=nummer, kundenavn=kundenavn, indeks=indeks, av=av,
        forkortelse=forkortelse, qr_url=qr_url,
    )
    sti.parent.mkdir(parents=True, exist_ok=True)
    bilde.save(sti)
    return sti


def _tegn(
    tekst: str,
    nummer: int,
    kundenavn: str = "",
    indeks: int = 1,
    av: int = 1,
    forkortelse: str | None = None,
    qr_url: str | None = None,
) -> Image.Image:
    """Tegn én etikett og returner bildet.

    Layout, venstre mot høyre:

        ┌────────────────────────────────────┐
        │  M4    Afras            [QR]       │   ← stort: type + nummer
        │        1/2                         │   ← lite: navn og teller
        └────────────────────────────────────┘

    Typen står som én bokstav fordi kokken skal lese den på tvers av bordet,
    og nummeret er det servitøren roper.
    """
    kort = (forkortelse or FORKORTELSER.get(tekst.lower(), tekst[:1])).upper()
    hovedtekst = f"{kort}{nummer}"

    stor = finn_font(46)
    liten = finn_font(19)

    # Mål opp innholdet på et engangsbilde før vi vet bredden.
    prov = ImageDraw.Draw(Image.new("L", (1, 1), 255))
    hovedbredde, _ = _mal(prov, hovedtekst, stor)

    teller = f"{indeks}/{av}" if av > 1 else ""
    navnelinje = kundenavn.split()[0] if kundenavn else ""
    sidebredde = max(
        (_mal(prov, navnelinje, liten)[0] if navnelinje else 0),
        (_mal(prov, teller, liten)[0] if teller else 0),
    )

    qr_side = TRYKK_HOYDE if qr_url else 0
    mellomrom = 10 if sidebredde else 0
    qr_mellomrom = 12 if qr_side else 0

    bredde = (
        MARG + hovedbredde + mellomrom + sidebredde + qr_mellomrom + qr_side + MARG
    )

    bilde = Image.new("L", (bredde, HOYDE), 255)
    tegner = ImageDraw.Draw(bilde)

    midt = TRYKK_TOPP + TRYKK_HOYDE // 2
    x = MARG

    # Stort: typebokstav + nummer, vertikalt sentrert i trykkflaten.
    tegner.text((x, midt), hovedtekst, font=stor, fill=0, anchor="lm")
    x += hovedbredde + mellomrom

    # Lite: fornavn øverst, teller under.
    if navnelinje or teller:
        if navnelinje and teller:
            tegner.text((x, TRYKK_TOPP + 14), navnelinje, font=liten, fill=0, anchor="lm")
            tegner.text((x, TRYKK_TOPP + 46), teller, font=liten, fill=0, anchor="lm")
        else:
            tegner.text((x, midt), navnelinje or teller, font=liten, fill=0, anchor="lm")
        x += sidebredde + qr_mellomrom

    if qr_url:
        qr = _qr_bilde(qr_url, qr_side)
        if qr is not None:
            bilde.paste(qr, (bredde - MARG - qr_side, TRYKK_TOPP))

    return bilde


def forhandsvis_binarisert(sti_inn: Path, sti_ut: Path, terskel: int = 128) -> Path:
    """Lagre det printeren faktisk trykker: ren svart/hvit, ingen gråtoner.

    Det er her tynn skrift forsvinner, så det er dette bildet som skal
    vurderes — ikke den pene PNG-en.
    """
    bilde = Image.open(sti_inn).convert("L")
    bilde.point(lambda p: 255 if p > terskel else 0).convert("1").save(sti_ut)
    return sti_ut

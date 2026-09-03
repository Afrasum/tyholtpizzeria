"""Sender en etikett til Brother PT-P300BT over /dev/rfcomm0.

Kjører labelmaker.py som egen prosess framfor å importere den. Tre grunner:
verktøyet er skrevet som CLI og kaller sys.exit() på feil, serieporten blir
garantert lukket når prosessen dør, og en hengt Bluetooth-forbindelse kan
drepes med tidsavbrudd i stedet for å låse appen.

Tidsavbruddet er ikke valgfritt. En PT-P300BT som har slått seg av selv, med
en RFCOMM-node som fortsatt ser gyldig ut, gir en åpen serial-kobling som
aldri svarer. Uten timeout står køen for godt, og det oppdager du først når
ordrene har stablet seg opp.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import tempfile
from pathlib import Path

from . import config, etikett

logg = logging.getLogger("tyholt.printer")


class PrinterFeil(Exception):
    """Printing feilet. Meldingen lagres på jobben og vises i admin."""


def tilgjengelig() -> bool:
    """Er printing i det hele tatt satt opp? Usann på utviklingsmaskin."""
    return bool(config.PRINTER_PORT) and config.LABELMAKER_STI.exists()


def skriv_ut(
    nummer: int,
    etiketter: list[dict],
    kundenavn: str = "",
) -> None:
    """Rendre og printe alle etikettene i en ordre som én strimmel.

    Én utskrift framfor én per pizza: printeren mater ut 2,5 cm før hver jobb,
    og de kan ikke gjenbrukes.
    """
    if not tilgjengelig():
        raise PrinterFeil(
            "Printing er ikke satt opp (mangler TP_PRINTER_PORT eller labelmaker.py)."
        )

    port = Path(config.PRINTER_PORT)
    if not port.exists():
        raise PrinterFeil(
            f"{port} finnes ikke. Er rfcomm bundet? "
            f"'sudo systemctl restart rfcomm-bind' på rpi5."
        )

    with tempfile.TemporaryDirectory(prefix="tyholt-etikett-") as katalog:
        png = etikett.render_strimmel(
            Path(katalog) / "strimmel.png",
            [{**e, "nummer": nummer, "kundenavn": kundenavn} for e in etiketter],
            qr_url=config.QR_URL if config.QR_PA_ETIKETT else None,
        )

        kommando = [
            sys.executable,
            str(config.LABELMAKER_STI),
            str(port),
            "-i",
            str(png),
            "-a",
            "1",  # auto-cut: -a tar en verdi i labelmaker.py, ikke store_true
        ]
        try:
            ferdig = subprocess.run(
                kommando,
                capture_output=True,
                text=True,
                timeout=config.PRINT_TIDSAVBRUDD,
                cwd=str(config.LABELMAKER_STI.parent),
            )
        except subprocess.TimeoutExpired as e:
            raise PrinterFeil(
                f"Printeren svarte ikke innen {config.PRINT_TIDSAVBRUDD} s. "
                "Sover den? Trykk en knapp på den og prøv på nytt."
            ) from e

    if ferdig.returncode != 0:
        siste = (ferdig.stderr or ferdig.stdout or "").strip().splitlines()
        raise PrinterFeil(siste[-1] if siste else f"labelmaker ga kode {ferdig.returncode}")

    # Verktøyet avslutter med 0 selv når printeren nekter, så vi ser i teksten.
    ut = ferdig.stdout or ""
    if "Refusing to continue" in ut or "not ready" in ut:
        raise PrinterFeil("Printeren melder at den ikke er klar (tape? deksel? strøm?).")
    if "successfully" not in ut:
        raise PrinterFeil("Uventet svar fra labelmaker — se logg.")

    logg.info(
        "strimmel printet: nr %s, %s etikett(er): %s",
        nummer, len(etiketter), ", ".join(e["tekst"] for e in etiketter),
    )


def status() -> dict:
    """Spør printeren om tape og feiltilstand. Til admin-visningen."""
    if not tilgjengelig():
        return {"ok": False, "melding": "printing ikke satt opp"}
    skript = (
        "import sys; sys.path.insert(0, %r)\n"
        "import serial, ptcbp, ptstatus\n"
        "from labelmaker import reset_printer\n"
        "s = serial.Serial(%r, timeout=8)\n"
        "reset_printer(s)\n"
        "s.write(ptcbp.serialize_control('get_status'))\n"
        "r = s.read(32)\n"
        "st = ptstatus.unpack_status(r)\n"
        "print(st.tape_width, st.err, st.phase_type, st.phase)\n"
        "s.close()\n"
    ) % (str(config.LABELMAKER_STI.parent), config.PRINTER_PORT)
    try:
        ferdig = subprocess.run(
            [sys.executable, "-c", skript],
            capture_output=True, text=True, timeout=15,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "melding": "printeren svarer ikke"}
    if ferdig.returncode != 0:
        return {"ok": False, "melding": (ferdig.stderr or "").strip().splitlines()[-1:] or "ukjent feil"}
    try:
        bredde, feil, fase_type, fase = ferdig.stdout.split()
        klar = feil == "0" and fase_type == "0" and fase == "0"
        return {"ok": klar, "tape_mm": int(bredde), "melding": "klar" if klar else "ikke klar"}
    except ValueError:
        return {"ok": False, "melding": "uleselig status"}

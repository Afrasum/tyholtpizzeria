"""Snakker med Brother PT-P300BT over /dev/rfcomm0.

VIKTIG DESIGNVALG: ÉN serietilkobling holdes åpen for hele appens levetid.

Første versjon kjørte labelmaker.py som egen prosess per etikett. Det virket
i test, og feilet i drift på en måte som er verdt å skrive ned: en
rfcomm-node kobler seg opp når porten åpnes og river ned når den lukkes, så
hver etikett ble en ny Bluetooth-tilkobling. Kom jobbene tett, låste printeren
en «Communication error» (err 0x4) som IKKE lar seg tømme — verken av reset,
ny bluetoothctl-tilkobling eller venting. Bare strøm av og på hjelper. Derfor
gikk den første etiketten gjennom og de fem neste ikke.

Nå eies porten av denne modulen, beskyttet av en lås. Det gir tre ting:
ingen veksling av tilkoblinger, en lenke som holdes varm så printeren ikke
sover, og at vi selv kan vente på at printeren blir klar framfor å gi opp.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from . import config, etikett

logg = logging.getLogger("tyholt.printer")

# Verktøyets moduler ligger i vendor/. De importeres først ved behov, slik at
# appen starter selv om katalogen mangler.
_vendor_lastet = False
_labelmaker = None
_encode = None
_ptcbp = None
_ptstatus = None
_serial = None


class PrinterFeil(Exception):
    """Printing feilet. Meldingen lagres på jobben og vises i admin."""


class PrinterLaast(PrinterFeil):
    """Printeren har låst en feiltilstand som krever strøm av og på.

    Egen klasse fordi den krever et menneske. Admin skiller den ut med
    beskjeden om hva som må gjøres.
    """


def _last_vendor() -> None:
    global _vendor_lastet, _labelmaker, _encode, _ptcbp, _ptstatus, _serial
    if _vendor_lastet:
        return
    vendor = str(config.LABELMAKER_STI.parent)
    if vendor not in sys.path:
        sys.path.insert(0, vendor)
    import labelmaker  # noqa: PLC0415
    import labelmaker_encode  # noqa: PLC0415
    import ptcbp  # noqa: PLC0415
    import ptstatus  # noqa: PLC0415
    import serial  # noqa: PLC0415

    _labelmaker, _encode = labelmaker, labelmaker_encode
    _ptcbp, _ptstatus, _serial = ptcbp, ptstatus, serial
    _vendor_lastet = True


def tilgjengelig() -> bool:
    """Er printing satt opp? Usann på utviklingsmaskin uten Bluetooth."""
    return bool(config.PRINTER_PORT) and config.LABELMAKER_STI.exists()


class Printer:
    """Eier serietilkoblingen. Én instans, all tilgang gjennom låsen."""

    def __init__(self) -> None:
        self._laas = threading.RLock()
        self._ser = None
        self._sist_brukt = 0.0

    # ── Tilkobling ─────────────────────────────────────────────────────────

    def _apne(self):
        if self._ser is not None and self._ser.is_open:
            return self._ser
        _last_vendor()
        port = Path(config.PRINTER_PORT)
        if not port.exists():
            raise PrinterFeil(
                f"{port} finnes ikke. Er rfcomm bundet? "
                "'sudo systemctl restart rfcomm-bind' på rpi5."
            )
        try:
            self._ser = _serial.Serial(str(port), timeout=10, write_timeout=10)
        except Exception as e:  # noqa: BLE001
            raise PrinterFeil(f"får ikke åpnet {port}: {e}") from e
        logg.info("serieport åpnet: %s", port)
        return self._ser

    def _lukk(self) -> None:
        """Lukk porten slik at neste kall kobler på nytt.

        Brukes bare når noe har gått galt. I normal drift står den åpen.
        """
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:  # noqa: BLE001, S110
                pass
            self._ser = None
            logg.info("serieport lukket for gjenoppkobling")

    # ── Status ─────────────────────────────────────────────────────────────

    def _les_status(self, ser):
        """Spør om status, og pass på at svaret vi leser faktisk er vårt.

        reset_input_buffer() er ikke en forsiktighetsdetalj: printeren sender
        FLERE statuspakker etter en utskrift (fase endret, printer, ferdig).
        Leser vi bare én, blir resten liggende, og neste forespørsel plukker
        opp en gammel pakke i stedet for sitt eget svar. Da er vi ute av synk
        med printeren, og den låser seg med err 0x4. Det var grunnen til at
        et par etiketter gikk gjennom for så å stoppe.
        """
        _last_vendor()
        ser.reset_input_buffer()
        _labelmaker.reset_printer(ser)
        ser.write(_ptcbp.serialize_control("get_status"))
        raa = ser.read(32)
        if len(raa) != 32:
            raise PrinterFeil(
                f"printeren svarte med {len(raa)} av 32 byte — lenken er nede"
            )
        return _ptstatus.unpack_status(raa)

    def _drener(self, ser, tidsavbrudd: float = 45.0) -> None:
        """Les ut alle statuspakkene printeren sender under og etter en jobb.

        Vi er ferdige når det har vært stille i STILLE_NOK sekunder. Da har
        tapen kommet ut, printeren er tilbake i ro, og bufferet er tomt til
        neste jobb.
        """
        STILLE_NOK = 2.0
        frist = time.monotonic() + tidsavbrudd
        sist_hort = time.monotonic()

        while time.monotonic() < frist:
            if ser.in_waiting >= 32:
                raa = ser.read(32)
                sist_hort = time.monotonic()
                if len(raa) == 32:
                    st = _ptstatus.unpack_status(raa)
                    if st.err != 0:
                        raise PrinterLaast(
                            f"printeren meldte feil under print "
                            f"(kode {hex(st.err)}). Skru den av og på, så "
                            "skriver køen seg ut av seg selv."
                        )
                continue
            if time.monotonic() - sist_hort >= STILLE_NOK:
                return
            time.sleep(0.1)

    def _vent_paa_klar(self, ser, tidsavbrudd: float = 25.0):
        """Poll til printeren er klar. Skiller mellom «travel» og «låst».

        Fase != 0 betyr at den holder på å printe, og da er venting riktig.
        err != 0 er en låst tilstand som venting aldri løser, så da avbryter
        vi med én gang framfor å brenne tidsavbruddet.
        """
        frist = time.monotonic() + tidsavbrudd
        sist = None
        while True:
            st = self._les_status(ser)
            sist = st
            if st.err == 0 and st.phase_type == 0 and st.phase == 0:
                return st
            if st.err != 0:
                raise PrinterLaast(
                    f"printeren har låst en feil (kode {hex(st.err)}). "
                    "Skru den av og på, så skriver køen seg ut av seg selv."
                )
            if time.monotonic() >= frist:
                raise PrinterFeil(
                    f"printeren ble ikke klar innen {tidsavbrudd:.0f} s "
                    f"(fase {sist.phase_type}/{sist.phase})"
                )
            time.sleep(0.5)

    def status(self) -> dict:
        """Til admin-visningen. Rapporterer ekte tilstand, ikke en gjetning."""
        if not tilgjengelig():
            return {"ok": False, "melding": "printing ikke satt opp"}
        with self._laas:
            try:
                ser = self._apne()
                st = self._les_status(ser)
            except PrinterFeil as e:
                self._lukk()
                return {"ok": False, "melding": str(e)}
            except Exception as e:  # noqa: BLE001
                self._lukk()
                return {"ok": False, "melding": f"{type(e).__name__}: {e}"}

            klar = st.err == 0 and st.phase_type == 0 and st.phase == 0
            if st.err != 0:
                melding = (
                    f"låst feil (kode {hex(st.err)}) — skru printeren av og på"
                )
            elif not klar:
                melding = "printer nå"
            else:
                melding = "klar"
            return {
                "ok": klar,
                "tape_mm": st.tape_width,
                "melding": melding,
                "laast": st.err != 0,
            }

    def hold_varm(self) -> None:
        """Ping printeren så Bluetooth-lenken ikke sovner.

        Auto-avslaget er det som starter hele ulykken: sover printeren, dør
        lenken, og da låser den en kommunikasjonsfeil. Billigere å holde den
        i live enn å hente den tilbake.
        """
        if not tilgjengelig():
            return
        with self._laas:
            if time.monotonic() - self._sist_brukt < 30:
                return
            try:
                ser = self._apne()
                self._les_status(ser)
                self._sist_brukt = time.monotonic()
            except Exception as e:  # noqa: BLE001
                logg.warning("holder ikke lenken varm: %s", e)
                self._lukk()

    # ── Printing ───────────────────────────────────────────────────────────

    def skriv_ut(
        self, nummer: int, etiketter: list[dict], kundenavn: str = ""
    ) -> None:
        """Rendre og printe alle etikettene i en ordre som én strimmel."""
        if not tilgjengelig():
            raise PrinterFeil(
                "Printing er ikke satt opp (mangler TP_PRINTER_PORT "
                "eller labelmaker.py)."
            )

        import tempfile  # noqa: PLC0415

        with tempfile.TemporaryDirectory(prefix="tyholt-etikett-") as katalog:
            png = etikett.render_strimmel(
                Path(katalog) / "strimmel.png",
                [{**e, "nummer": nummer, "kundenavn": kundenavn} for e in etiketter],
                qr_url=config.QR_URL if config.QR_PA_ETIKETT else None,
            )
            _last_vendor()
            data = _encode.read_png(str(png))

        with self._laas:
            try:
                ser = self._apne()
                st = self._vent_paa_klar(ser)

                _labelmaker.configure_printer(
                    ser,
                    len(data) // 16,
                    (st.tape_type, st.tape_width, st.tape_length),
                    compress=True,
                    chaining=False,
                    auto_cut=True,
                    # Mater etiketten forbi kniven. Se PRINT_SLUTTMARG.
                    end_margin=config.PRINT_SLUTTMARG,
                )
                for linje in _encode.encode_raster_transfer(data, False):
                    ser.write(linje)
                ser.write(_ptcbp.serialize_control("print"))

                # Les ut ALLE pakkene, ikke bare den forste. Se _drener.
                self._drener(ser)
                self._sist_brukt = time.monotonic()

            except PrinterFeil:
                # Porten beholdes ved låst feil: den er ikke problemet, og
                # gjenoppkobling er nettopp det som utløste feilen.
                raise
            except Exception as e:  # noqa: BLE001
                self._lukk()
                raise PrinterFeil(f"{type(e).__name__}: {e}") from e

        logg.info(
            "strimmel printet: nr %s, %s etikett(er): %s",
            nummer, len(etiketter), ", ".join(e["tekst"] for e in etiketter),
        )


printer = Printer()


def skriv_ut(nummer: int, etiketter: list[dict], kundenavn: str = "") -> None:
    printer.skriv_ut(nummer, etiketter, kundenavn)


def status() -> dict:
    return printer.status()


def hold_varm() -> None:
    printer.hold_varm()

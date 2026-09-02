#!/usr/bin/env python3
"""Legg til en ingress-regel i en cloudflared-config, rett før catch-all.

    python3 cf_ingress.py /etc/cloudflared/config.yml falch.afrasum.dev 8008

Idempotent: gjør ingenting hvis vertsnavnet allerede står der. Avbryter med
feilkode hvis catch-all-regelen ikke finnes, slik at kalleren kan rulle tilbake
i stedet for å skrive en halvferdig config.
"""

import sys


def main(sti, vert, port):
    with open(sti, encoding="utf-8") as f:
        linjer = f.read().splitlines(keepends=True)

    if any(vert in l for l in linjer):
        print(f"    {vert} står allerede i {sti}")
        return 0

    for i, l in enumerate(linjer):
        if "http_status:404" in l:
            linjer.insert(i, f"  - hostname: {vert}\n    service: http://localhost:{port}\n")
            break
    else:
        print(f"    fant ingen catch-all (http_status:404) i {sti} — avbryter", file=sys.stderr)
        return 1

    with open(sti, "w", encoding="utf-8") as f:
        f.write("".join(linjer))
    print(f"    la til {vert} -> localhost:{port}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1], sys.argv[2], sys.argv[3]))

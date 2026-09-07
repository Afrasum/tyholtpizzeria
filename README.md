# Tyholt Pizzeria

Bestillingssystem for et pop-up pizzeria: kundeside, admin-dashbord for
kjøkken og kasse, og en henteskjerm som står vendt mot rommet. FastAPI og
SQLite, kjørt på rpi5 og eksponert gjennom cloudflared-tunnelen `rpi`.

    Cloudflare → cloudflared (tunnel «rpi») → localhost:8009 → uvicorn

Etikettene printes på en Brother PT-P300BT over Bluetooth (`/dev/rfcomm0`).

## To tilstander

Bryteren «Steng» i admin styrer hele kundesida, ikke bare skjemaet:

| `manuelt_stengt` | `/` rendrer | Kvitteringene |
|---|---|---|
| `0` | `kunde/forside.html` — meny og bestilling | `/kvittering/{id}` virker |
| `1` | `kunde/hjem.html` — nettsida | alle svarer 404 |

`/helga` (`kunde/helga.html`) er permanent og staar i begge tilstander.

Teksten under «Hvem vi er» er `minne.OM_OSS` — ett strengelement per avsnitt,
tom til noen skriver dem. Er den tom, hopper malen over avsnittene framfor aa
vise en plassholder. Det er en test paa det.

To ULIKE maler, ikke en if-grein: forside.html er tunet for en 34 rem
telefonspalte med klistrekurv og pluss/minus-felt, hjem.html er en bred
nettside. Stilarket til nettsida har `n-`-prefiks paa hver klasse, fordi
`.topp` og `.antall` fra bestillingssida ellers slaar inn i den.

Etter 4.–5. september 2026 staar den paa `1`, og sida er et minne. Tallene
ligger frosset i `app/minne.py` — de hentes ikke levende, se docstringen der.

Kvitteringene er stengt fordi `/kvittering/{id}` tar en gjettbar id og viser
fornavn og e-postadresse. Aapner vi for en ny pop-up virker de igjen, og da er
ogsaa de gamle naabare — vil vi unngaa det maa de gamle radene toemmes eller
anonymiseres foer vi aapner.

## Domener

| URL | Hva |
|---|---|
| `tyholtpizzeria.com` | kundesida — meny og bestilling |
| `/admin` | ordrekø, statusknapper, utsolgt, Vipps-mottaker |
| `/skjerm` | henteskjermen — kun numre, ingen navn |

## Kjøre lokalt

    uv run uvicorn app.main:app --reload --port 8123

Uten `TP_PRINTER_PORT` er printing av, og uten `TP_SMTP_VERT` logges
e-postene i stedet for å sendes. Da kjører alt likt på Mac som på Pi.

    uv run pytest -q

## Oppsett på rpi5

Én gang:

    ssh rpi5 'git clone git@github.com:Afrasum/tyholtpizzeria.git ~/projects/tyholtpizzeria'
    ssh -t rpi5 "sudo sh ~/projects/tyholtpizzeria/deploy/install-system.sh"
    ssh -t rpi5 "sudo sh ~/projects/tyholtpizzeria/deploy/install-app.sh"
    ssh rpi5 'cloudflared tunnel route dns rpi tyholtpizzeria.afrasum.dev'

Begge skriptene er idempotente. `install-system.sh` skyter ingress-regelen inn
i `/etc/cloudflared/config.yml` rett før catch-all, med backup og validering og
rullback hvis valideringen feiler.

## Deploye endringer

    ssh rpi5 'git -C ~/projects/tyholtpizzeria pull'
    ssh -t rpi5 "sudo systemctl restart tyholtpizzeria"

Restart er nødvendig: malene, stilarket og eventuelle skjemamigreringer leses
ved oppstart. Versjonsnøkkelen på `/static` følger filenes mtime, så
Cloudflare-cachen brytes av seg selv når tjenesten starter på nytt.

## Viktige begrensninger

- **Én uvicorn-arbeider.** Tildelingen av dagsnummer bygger på SQLites
  skrivelås i én prosess, og printeren tåler bare én tilkobling om gangen.
- **Databasen ligger utenfor git-treet** (`~/data/tyholtpizzeria/base.db`), med
  backup hvert minutt til `backup/` ved siden av.
- **Klokka stenger ikke.** Bare den manuelle bryteren i admin gjør det.

## Filer

| Fil | Rolle |
|---|---|
| `app/ordrer.py` | kjernen: dagsnummer, statusflyt, oppslag |
| `app/jobber.py` | jobbkø, én arbeidertråd per type |
| `app/printer.py` | eier serietilkoblingen til etikettprinteren |
| `app/schema.sql` | skjema, kjøres idempotent ved oppstart |
| `deploy/install-system.sh` | cloudflared-ingress, krever sudo |
| `deploy/install-app.sh` | venv, systemd-units, backup-timer |
| `deploy/backup.sh` | minuttkopi av basen, kjøres av timeren |
| `vendor/PT-P300BT/` | tredjeparts printerbibliotek |

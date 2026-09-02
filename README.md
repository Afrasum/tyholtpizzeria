# tyholtpizzeria.afrasum.dev

Statisk side servert av Caddy på rpi5, eksponert gjennom cloudflared-tunnelen
`rpi`. Foreløpig bare en plassholderside.

    Cloudflare → cloudflared (tunnel «rpi») → localhost:8009 → Caddy → dette repoet

## Oppsett på rpi5

Klon repoet og kjør systemoppsettet én gang:

    ssh rpi5 'git clone git@github.com:Afrasum/tyholtpizzeria.git ~/projects/tyholtpizzeria'
    ssh -t rpi5 "sudo sh ~/projects/tyholtpizzeria/deploy/install-system.sh"
    ssh rpi5 'cloudflared tunnel route dns rpi tyholtpizzeria.afrasum.dev'

`install-system.sh` er idempotent: den legger Caddyfilen og systemd-unitet på
plass, og skyter inn ingress-regelen i `/etc/cloudflared/config.yml` rett før
catch-all. Configen backes opp og valideres, og rulles tilbake hvis den feiler.

## Publisere endringer

Caddy serverer arbeidstreet direkte, så `git pull` er publiseringen:

    ssh rpi5 'git -C ~/projects/tyholtpizzeria pull'

Ingen restart trengs for innholdsendringer. Endrer du `deploy/`-filene må
`install-system.sh` kjøres på nytt.

## Filer

| Fil | Rolle |
|---|---|
| `index.html`, `css/stil.css` | selve siden |
| `deploy/tyholtpizzeria.Caddyfile` | Caddy-config, lytter på `:8009` |
| `deploy/tyholtpizzeria-site.service` | systemd-unit som kjører Caddy |
| `deploy/install-system.sh` | systemoppsett, krever sudo |
| `deploy/cf_ingress.py` | legger ingress-regelen inn i cloudflared-configen |

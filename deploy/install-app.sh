#!/bin/sh
# Systemnivaa-oppsett for pizzeria-appen paa rpi5. Krever sudo.
#
#   ssh -t rpi5 "sudo sh ~/projects/tyholtpizzeria/deploy/install-app.sh"
#
# Idempotent. Bytter port 8009 fra Caddy (plassholdersida) til uvicorn.
# Cloudflared-ingressen peker alt paa 8009, saa den roeres ikke - det er
# nettopp derfor vi beholdt porten. Rollback er aa reversere de to
# systemctl-linjene.

set -eu

REPO=/home/afras/projects/tyholtpizzeria

echo "==> rfcomm-binding (etikettprinteren)"
install -m 644 "$REPO/deploy/rfcomm-bind.service" /etc/systemd/system/rfcomm-bind.service
systemctl daemon-reload
systemctl enable --now rfcomm-bind.service
if [ -e /dev/rfcomm0 ]; then
	echo "    /dev/rfcomm0 er bundet"
else
	echo "    !! /dev/rfcomm0 mangler - er printeren av? Appen starter likevel,"
	echo "       men etikettjobber vil feile til den er tilbake."
fi

echo "==> sikkerhetskopiering"
install -m 644 "$REPO/deploy/tyholt-backup.service" /etc/systemd/system/tyholt-backup.service
install -m 644 "$REPO/deploy/tyholt-backup.timer"   /etc/systemd/system/tyholt-backup.timer
systemctl daemon-reload
systemctl enable --now tyholt-backup.timer
echo "    kvarterskopier til ~/data/tyholtpizzeria/backup/"

echo "==> app-unit"
install -m 644 "$REPO/deploy/tyholtpizzeria.service" /etc/systemd/system/tyholtpizzeria.service

if [ ! -f "$REPO/.env" ]; then
	echo "    !! $REPO/.env mangler. Lag den foerst (se .env.eksempel)."
	exit 1
fi

echo "==> gir 8009 fra Caddy til uvicorn"
# Plassholdersida og appen kan ikke lytte paa samme port samtidig.
systemctl disable --now tyholtpizzeria-site.service 2>/dev/null || true
echo "    Caddy-unitet er avslaatt (reverser med: systemctl enable --now tyholtpizzeria-site)"

systemctl daemon-reload
systemctl enable --now tyholtpizzeria.service
systemctl restart tyholtpizzeria.service

echo "==> venter paa at appen svarer"
i=0
while [ $i -lt 20 ]; do
	if curl -fsS -o /dev/null http://127.0.0.1:8009/helse 2>/dev/null; then
		echo "    appen svarer paa 8009"
		exit 0
	fi
	i=$((i + 1))
	sleep 1
done

echo "    !! appen svarte ikke innen 20 s. Siste logg:"
journalctl -u tyholtpizzeria.service -n 20 --no-pager
exit 1

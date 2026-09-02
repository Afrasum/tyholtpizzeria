#!/bin/sh
# Systemnivå-oppsett for tyholtpizzeria.afrasum.dev på rpi5. Krever sudo.
#
#   ssh -t rpi5 "sudo sh ~/projects/tyholtpizzeria/deploy/install-system.sh"
#
# Idempotent: kan kjøres flere ganger. Tar backup av cloudflared-configen før
# den røres, validerer før restart, og ruller tilbake hvis valideringen feiler.

set -eu

REPO=/home/afras/projects/tyholtpizzeria
CF=/etc/cloudflared/config.yml
VERT=tyholtpizzeria.afrasum.dev
PORT=8009

echo "==> Caddy-config og site-unit"
install -m 644 "$REPO/deploy/tyholtpizzeria.Caddyfile"    /etc/caddy/tyholtpizzeria.Caddyfile
install -m 644 "$REPO/deploy/tyholtpizzeria-site.service" /etc/systemd/system/tyholtpizzeria-site.service

caddy validate --adapter caddyfile --config /etc/caddy/tyholtpizzeria.Caddyfile >/dev/null
echo "    Caddyfile validerer"

systemctl daemon-reload
systemctl enable --now tyholtpizzeria-site.service
systemctl restart tyholtpizzeria-site.service
echo "    tyholtpizzeria-site.service kjører"

echo "==> Cloudflared ingress"
if grep -q "$VERT" "$CF"; then
	echo "    $VERT ligger allerede i $CF — hopper over"
else
	SIKKER="$CF.bak.$(date +%Y%m%d%H%M%S)"
	cp -p "$CF" "$SIKKER"
	echo "    backup: $SIKKER"

	# Sett inn den nye regelen rett før catch-all-regelen på slutten.
	if ! python3 "$REPO/deploy/cf_ingress.py" "$CF" "$VERT" "$PORT"; then
		echo "    !! kunne ikke redigere ingress — ruller tilbake"
		cp -p "$SIKKER" "$CF"
		exit 1
	fi

	# --config må stå FØR subkommandoen, ellers ignoreres den og cloudflared
	# validerer standardconfigen i stedet.
	if cloudflared --config "$CF" tunnel ingress validate; then
		echo "    ingress validerer"
	else
		echo "    !! ingress feilet validering — ruller tilbake"
		cp -p "$SIKKER" "$CF"
		exit 1
	fi

	systemctl restart cloudflared.service
	echo "    cloudflared restartet"
fi

echo
echo "Ferdig. Gjenstår (kjøres som afras, uten sudo):"
echo "  cloudflared tunnel route dns rpi $VERT"

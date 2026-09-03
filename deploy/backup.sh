#!/bin/sh
# Sikkerhetskopi av ordrebasen. Kjores av tyholt-backup.timer hvert minutt.
#
# .backup i sqlite3 er trygg mot en base som skrives til samtidig - en ren
# filkopi kan fange en halvskrevet WAL.
#
# Basen er noen titalls kB, sa en kopi tar millisekunder og komprimert fyller
# den nesten ingenting. Vi beholder de 360 nyeste, altsa seks timer med
# minuttkopier - mer enn nok til a spole forbi enhver tabbe pa en kveld.
#
# Filnavnene sorterer kronologisk leksikografisk (base-YYYYmmdd-HHMMSS), sa
# vi bruker find | sort framfor "ls -t". Det er ikke pedanteri: ls er aliaset
# til eza pa utviklingsmaskinen, og eza tolker -t som et felt-argument.

set -eu

BASE=${TP_DB:-/home/afras/data/tyholtpizzeria/base.db}
KATALOG=$(dirname "$BASE")/backup
BEHOLD=360

[ -f "$BASE" ] || exit 0
mkdir -p "$KATALOG"

LISTE=$(find "$KATALOG" -name 'base-*.db.gz' -type f 2>/dev/null | sort)

# Hopp over hvis basen ikke er endret siden forrige kopi. Ellers ville en
# stille kveld skrevet 360 identiske filer.
if [ -n "$LISTE" ]; then
	SISTE=$(printf '%s\n' "$LISTE" | tail -1)
	if [ ! "$BASE" -nt "$SISTE" ]; then
		exit 0
	fi
fi

MAL="$KATALOG/base-$(date +%Y%m%d-%H%M%S).db"
sqlite3 "$BASE" ".backup '$MAL'"
gzip -f "$MAL"

# Rydd de eldste.
LISTE=$(find "$KATALOG" -name 'base-*.db.gz' -type f 2>/dev/null | sort)
ANTALL=$(printf '%s\n' "$LISTE" | grep -c . || true)
if [ "$ANTALL" -gt "$BEHOLD" ]; then
	printf '%s\n' "$LISTE" | head -n $((ANTALL - BEHOLD)) | while read -r f; do
		[ -n "$f" ] && rm -f "$f"
	done
fi

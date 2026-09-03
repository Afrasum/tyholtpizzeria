#!/bin/sh
# Sikkerhetskopi av ordrebasen. Kjores av tyholt-backup.timer hvert minutt.
#
# Bruker Pythons sqlite3.Connection.backup() framfor sqlite3-kommandoen.
# Grunnen er konkret: sqlite3-CLI-en er IKKE installert pa rpi5, og med den
# varianten gikk unitet "Finished ... successfully" hvert kvarter uten a
# kopiere en eneste byte. Python-modulen ligger i venv-en vi alt har.
#
# .backup er trygg mot en base som skrives til samtidig - en ren filkopi kan
# fange en halvskrevet WAL.
#
# Basen er noen titalls kB, sa en kopi tar millisekunder. Vi beholder de 360
# nyeste, altsa seks timer med minuttkopier.
#
# Filnavnene sorterer kronologisk leksikografisk (base-YYYYmmdd-HHMMSS), sa
# vi bruker find | sort framfor "ls -t": ls er aliaset til eza pa
# utviklingsmaskinen, og eza tolker -t som feltargument.

set -eu

REPO=$(cd "$(dirname "$0")/.." && pwd)
PYTHON=$REPO/.venv/bin/python
BASE=${TP_DB:-/home/afras/data/tyholtpizzeria/base.db}
KATALOG=$(dirname "$BASE")/backup
BEHOLD=360

if [ ! -x "$PYTHON" ]; then
	echo "backup: finner ikke $PYTHON" >&2
	exit 1
fi

# Ingen base ennaa er greit - appen har ikke startet forste gang.
[ -f "$BASE" ] || exit 0

mkdir -p "$KATALOG"

# Hopp over hvis basen ikke er endret siden forrige kopi. Ellers ville en
# stille kveld skrevet 360 identiske filer.
LISTE=$(find "$KATALOG" -name 'base-*.db.gz' -type f 2>/dev/null | sort)
if [ -n "$LISTE" ]; then
	SISTE=$(printf '%s\n' "$LISTE" | tail -1)
	if [ ! "$BASE" -nt "$SISTE" ]; then
		exit 0
	fi
fi

MAL="$KATALOG/base-$(date +%Y%m%d-%H%M%S).db"

"$PYTHON" - "$BASE" "$MAL" <<'PY'
import sqlite3
import sys

kilde, mal = sys.argv[1], sys.argv[2]
# Skrivelaas tas ikke: backup() itererer over sider og gjentar seg selv hvis
# basen endres underveis, sa bestillinger kan ga inn mens vi kopierer.
inn = sqlite3.connect(f"file:{kilde}?mode=ro", uri=True)
ut = sqlite3.connect(mal)
try:
    inn.backup(ut)
finally:
    ut.close()
    inn.close()
PY

gzip -f "$MAL"

# Rydd de eldste.
LISTE=$(find "$KATALOG" -name 'base-*.db.gz' -type f 2>/dev/null | sort)
ANTALL=$(printf '%s\n' "$LISTE" | grep -c . || true)
if [ "$ANTALL" -gt "$BEHOLD" ]; then
	printf '%s\n' "$LISTE" | head -n $((ANTALL - BEHOLD)) | while read -r f; do
		[ -n "$f" ] && rm -f "$f"
	done
fi

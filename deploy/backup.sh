#!/bin/sh
# Sikkerhetskopi av ordrebasen. Kjores av backup.timer hvert kvarter.
#
# .backup i sqlite3 er trygg mot en base som skrives til samtidig - en ren
# filkopi kan fange en halvskrevet WAL. Vi beholder de 48 nyeste, altsa
# 12 timer med kvarterskopier.

set -eu

BASE=${TP_DB:-/home/afras/data/tyholtpizzeria/base.db}
KATALOG=$(dirname "$BASE")/backup
BEHOLD=48

[ -f "$BASE" ] || exit 0
mkdir -p "$KATALOG"

MAL="$KATALOG/base-$(date +%Y%m%d-%H%M%S).db"
sqlite3 "$BASE" ".backup '$MAL'"
gzip -f "$MAL"

# Rydd de eldste.
ls -1t "$KATALOG"/base-*.db.gz 2>/dev/null | tail -n +$((BEHOLD + 1)) | while read -r f; do
	rm -f "$f"
done

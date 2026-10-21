#!/usr/bin/env bash
# filmNotes database backup - WAL-safe, gzipped, with retention pruning.
#
# Uses the SQLite online-backup API (never cp a live WAL database!).
# Designed for weekly cron; keeps the newest $KEEP backups (default 16).
#
# Cron example (Sundays 03:00, paths abridged - use your real install path):
#   0 3 * * 0 /path/to/filmNotes/scripts/backup.sh >> /path/to/filmNotes/backups/backup.log 2>&1
#
# Env overrides:
#   FILMNOTES_DB         database to back up   (default <app>/data/filmnotes.sqlite)
#   FILMNOTES_BACKUP_DIR output directory      (default <app>/backups)
#   FILMNOTES_BACKUP_KEEP files to retain      (default 16)
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB="${FILMNOTES_DB:-$APP_DIR/data/filmnotes.sqlite}"
DIR="${FILMNOTES_BACKUP_DIR:-$APP_DIR/backups}"
KEEP="${FILMNOTES_BACKUP_KEEP:-16}"
PY="$APP_DIR/.venv/bin/python"

[ -f "$DB" ] || { echo "backup: database not found at $DB" >&2; exit 1; }
[ -x "$PY" ] || PY="$(command -v python3)"
mkdir -p "$DIR"

STAMP="$(date +%Y-%m-%d_%H%M)"
OUT="$DIR/filmnotes-$STAMP.sqlite.gz"
TMP="$OUT.tmp"

"$PY" - "$DB" "$TMP" <<'PYEOF'
import sqlite3, sys, gzip
src, dst = sys.argv[1], sys.argv[2]
with sqlite3.connect(src) as s, sqlite3.connect(dst) as d:
    s.backup(d)                       # consistent snapshot even while serving
with open(dst, "rb") as f, gzip.open(dst + ".gz", "wb", 9) as g:
    g.writelines(f)
PYEOF
mv "$TMP.gz" "$OUT"
rm -f "$TMP"

# verify the snapshot opens and reports integrity before counting it good
"$PY" - "$OUT" <<'PYEOF'
import sqlite3, sys, gzip, tempfile, os
with gzip.open(sys.argv[1], "rb") as g:
    tmp = tempfile.mktemp(suffix=".sqlite")
    with open(tmp, "wb") as f:
        f.writelines(g)
con = sqlite3.connect(tmp)
ok = con.execute("PRAGMA integrity_check").fetchone()[0]
rolls = con.execute("SELECT COUNT(*) FROM rolls").fetchone()[0]
con.close(); os.unlink(tmp)
if ok != "ok":
    sys.exit(f"integrity_check failed: {ok}")
print(f"verified {sys.argv[1]} (integrity ok, {rolls} rolls)")
PYEOF

# prune: keep the newest $KEEP
ls -1t "$DIR"/filmnotes-*.sqlite.gz 2>/dev/null | tail -n +$((KEEP + 1)) | \
while read -r f; do rm -f "$f"; echo "pruned $f"; done

echo "backup complete: $OUT"

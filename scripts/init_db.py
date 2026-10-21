#!/usr/bin/env python3
"""filmNotes database init / restore helper.

Create a fresh database (schema + seed cameras/film), or restore one from
a backup.sh snapshot:

  .venv/bin/python scripts/init_db.py                     # data/filmnotes.sqlite
  .venv/bin/python scripts/init_db.py --db /path/to.sqlite
  .venv/bin/python scripts/init_db.py --from-backup backups/filmnotes-2026-01-01_0300.sqlite.gz
                                                          # restore into --db path
                                                          # (add --force to overwrite)

Idempotent: running it against an existing database only applies pending
migrations; it never deletes data. Stop the server before restoring.
"""
import argparse
import gzip
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from filmnotes import db  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="init or restore the filmNotes db")
    ap.add_argument("--db", default="data/filmnotes.sqlite")
    ap.add_argument("--from-backup", default=None,
                    help="gzipped sqlite snapshot from backup.sh to restore")
    ap.add_argument("--force", action="store_true",
                    help="allow --from-backup to overwrite an existing db")
    args = ap.parse_args()

    if args.from_backup:
        if not os.path.exists(args.from_backup):
            sys.exit(f"backup file not found: {args.from_backup}")
        if os.path.exists(args.db) and not args.force:
            sys.exit(f"{args.db} already exists; pass --force to overwrite "
                     "(stop the server first!)")
        for suffix in ("", "-wal", "-shm"):
            p = args.db + suffix
            if os.path.exists(p):
                os.unlink(p)
        os.makedirs(os.path.dirname(os.path.abspath(args.db)), exist_ok=True)
        with gzip.open(args.from_backup, "rb") as g, open(args.db, "wb") as f:
            shutil.copyfileobj(g, f)
        print(f"restored {args.from_backup} -> {args.db}")

    os.makedirs(os.path.dirname(os.path.abspath(args.db)), exist_ok=True)
    conn = db.connect(args.db)
    db.init_db(conn)
    cams = conn.execute("SELECT COUNT(*) c FROM cameras").fetchone()["c"]
    films = conn.execute("SELECT COUNT(*) c FROM films").fetchone()["c"]
    rolls = conn.execute("SELECT COUNT(*) c FROM rolls").fetchone()["c"]
    ok = conn.execute("PRAGMA integrity_check").fetchone()[0]
    print(f"{args.db}: integrity={ok} cameras={cams} films={films} rolls={rolls}")
    conn.close()


if __name__ == "__main__":
    main()

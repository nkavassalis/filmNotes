"""Hermetic tests for scripts/backup.sh and scripts/init_db.py.

Uses throwaway DBs and FILMNOTES_BACKUP_DIR overrides; never touches the
real data/ or backups/ directories.
"""
import gzip
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKUP = ROOT / "scripts" / "backup.sh"
INIT = ROOT / "scripts" / "init_db.py"
PY = sys.executable


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def make_db(path, rolls=2):
    run([PY, str(INIT), "--db", str(path)])
    con = sqlite3.connect(path)
    cam = con.execute("SELECT id FROM cameras LIMIT 1").fetchone()[0]
    film = con.execute("SELECT id FROM films LIMIT 1").fetchone()[0]
    loc = con.execute("SELECT id FROM locations LIMIT 1").fetchone()
    if loc is None:
        cur = con.execute("INSERT INTO locations(name, visited_at, created_at) "
                          "VALUES('T', '2026-01-01 10:00', 'x')")
        loc = (cur.lastrowid,)
    for i in range(rolls):
        con.execute("INSERT INTO rolls(roll_no, camera_id, film_id, shot_at, "
                    "created_at) VALUES(?,?,?,?,?)",
                    (f"r{i}", cam, film, "2026-01-01 10:00", "x"))
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM rolls").fetchone()[0]
    con.close()
    return n


def test_init_creates_seeded_db(tmp_path):
    db = tmp_path / "fresh.sqlite"
    r = run([PY, str(INIT), "--db", str(db)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "integrity=ok" in r.stdout and "cameras=6" in r.stdout
    # idempotent
    r = run([PY, str(INIT), "--db", str(db)])
    assert r.returncode == 0 and "cameras=6" in r.stdout


def test_backup_verifies_and_prunes(tmp_path):
    db = tmp_path / "live.sqlite"
    rolls = make_db(db)
    bdir = tmp_path / "backups"
    env = {"FILMNOTES_DB": str(db), "FILMNOTES_BACKUP_DIR": str(bdir),
           "FILMNOTES_BACKUP_KEEP": "2", "PATH": "/usr/bin:/bin"}
    # two old decoy backups so pruning has something to cut
    bdir.mkdir()
    for name in ("filmnotes-2025-01-01_0300.sqlite.gz",
                 "filmnotes-2025-01-08_0300.sqlite.gz"):
        (bdir / name).write_bytes(b"junk")
    r = run(["bash", str(BACKUP)], env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "integrity ok" in r.stdout and f"{rolls} rolls" in r.stdout
    kept = sorted(p.name for p in bdir.glob("filmnotes-*.sqlite.gz"))
    assert len(kept) == 2          # KEEP=2: newest real backup + one decoy
    assert "pruned" in r.stdout
    # the kept real backup is a valid gzip sqlite snapshot
    newest = max((p for p in bdir.glob("*.gz") if p.stat().st_size > 100),
                 key=lambda p: p.stat().st_mtime)
    with gzip.open(newest, "rb") as g:
        snap = tmp_path / "snap.sqlite"
        snap.write_bytes(g.read())
    con = sqlite3.connect(snap)
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert con.execute("SELECT COUNT(*) FROM rolls").fetchone()[0] == rolls
    con.close()


def test_restore_roundtrip(tmp_path):
    db = tmp_path / "live.sqlite"
    rolls = make_db(db, rolls=3)
    bdir = tmp_path / "backups"
    env = {"FILMNOTES_DB": str(db), "FILMNOTES_BACKUP_DIR": str(bdir),
           "PATH": "/usr/bin:/bin"}
    assert run(["bash", str(BACKUP)], env=env).returncode == 0
    snap = next(bdir.glob("filmnotes-*.sqlite.gz"))
    restored = tmp_path / "restored.sqlite"
    r = run([PY, str(INIT), "--db", str(restored), "--from-backup", str(snap)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"rolls={rolls}" in r.stdout
    # refuses to clobber an existing db without --force
    r = run([PY, str(INIT), "--db", str(restored), "--from-backup", str(snap)])
    assert r.returncode != 0 and "--force" in (r.stdout + r.stderr)
    r = run([PY, str(INIT), "--db", str(restored), "--from-backup",
             str(snap), "--force"])
    assert r.returncode == 0 and f"rolls={rolls}" in r.stdout


def test_backup_fails_cleanly_without_db(tmp_path):
    env = {"FILMNOTES_DB": str(tmp_path / "nope.sqlite"),
           "FILMNOTES_BACKUP_DIR": str(tmp_path / "b"), "PATH": "/usr/bin:/bin"}
    r = run(["bash", str(BACKUP)], env=env)
    assert r.returncode != 0 and "not found" in (r.stdout + r.stderr)

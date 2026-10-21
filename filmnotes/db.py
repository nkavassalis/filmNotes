"""ALL SQL lives here. Routes stay thin.

Schema notes
------------
* settings is a simple key/value table (server-side user settings, e.g.
  theme). Whitelist + validation live in web.py, storage is dumb.
* rolls references cameras/films/locations by id (FKs ON).
* list_cameras/list_films carry used_count + last_used so the UI can sort
  dropdowns "most recently used first" without a second query.
* Timestamps are UTC ISO-8601 strings (second precision), sortable as text.
"""
import sqlite3
from datetime import datetime, timezone

SEED_CAMERAS = [
    "Leica MP", "Leica M6", "Canon 1V",
    "Pentax 67", "Bronica SQ-A", "Pentax 645N2",
]

SEED_FILMS = [
    "Fujifilm Provia 100", "Fujifilm Velvia 50", "Fujifilm Velvia 100",
    "Kodak Portra 160", "Kodak Portra 400", "Kodak Portra 800",
    "Ilford Delta 100", "Ilford Delta 400",
    "Ilford XP2 400", "Ilford HP5 400",
    "Kodak Tri-X 400",
    "Kodak T-Max 100", "Kodak T-Max 400", "Kodak T-Max 3200",
    "Fujifilm Acros II",
]

DEFAULT_SETTINGS = {"theme": "auto", "show_times": "0"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lenses (
  id         INTEGER PRIMARY KEY,
  name       TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cameras (
  id         INTEGER PRIMARY KEY,
  name       TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS films (
  id         INTEGER PRIMARY KEY,
  name       TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS locations (
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL,
  note        TEXT NOT NULL DEFAULT '',
  lat         REAL,
  lon         REAL,
  visited_at  TEXT NOT NULL DEFAULT '',
  created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rolls (
  id          INTEGER PRIMARY KEY,
  roll_no     TEXT NOT NULL DEFAULT '',
  camera_id   INTEGER NOT NULL REFERENCES cameras(id),
  film_id     INTEGER NOT NULL REFERENCES films(id),
  lens_id     INTEGER REFERENCES lenses(id),
  note        TEXT NOT NULL DEFAULT '',
  shot_at     TEXT NOT NULL DEFAULT '',
  created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS roll_locations (
  roll_id     INTEGER NOT NULL REFERENCES rolls(id),
  location_id INTEGER NOT NULL REFERENCES locations(id),
  note        TEXT NOT NULL DEFAULT '',
  visited_at  TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (roll_id, location_id)
);
CREATE INDEX IF NOT EXISTS idx_roll_locations_loc  ON roll_locations(location_id);
CREATE INDEX IF NOT EXISTS idx_roll_locations_roll ON roll_locations(roll_id);
CREATE INDEX IF NOT EXISTS idx_rolls_camera   ON rolls(camera_id);
CREATE INDEX IF NOT EXISTS idx_rolls_film     ON rolls(film_id);
"""


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_local():
    """Wall-clock 'YYYY-MM-DD HH:MM' (the user's shooting date default).

    shot_at/visited_at are LOCAL naive datetimes as entered by the user
    (datetime-local inputs); fixed-width so plain string sort orders them.
    created_at stays UTC ISO for auditing.
    """
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def connect(path):
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _migrate(conn):
    """Additive migrations for pre-existing databases."""
    def cols(table):
        return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    if "shot_at" not in cols("rolls"):
        conn.execute("ALTER TABLE rolls ADD COLUMN shot_at TEXT NOT NULL DEFAULT ''")
        conn.execute("UPDATE rolls SET shot_at = "
                     "replace(substr(created_at, 1, 16), 'T', ' ')")
    if "visited_at" not in cols("locations"):
        conn.execute("ALTER TABLE locations ADD COLUMN visited_at TEXT NOT NULL DEFAULT ''")
        conn.execute("UPDATE locations SET visited_at = "
                     "replace(substr(created_at, 1, 16), 'T', ' ')")
    # v0.2: rolls.location_id -> roll_locations junction (a roll accumulates
    # locations; New Location attaches to the current roll).
    if "location_id" in cols("rolls"):
        conn.execute(
            "INSERT OR IGNORE INTO roll_locations"
            "(roll_id, location_id, note, visited_at) "
            "SELECT r.id, r.location_id, '', r.shot_at FROM rolls r "
            "WHERE r.location_id IS NOT NULL "
            "AND EXISTS (SELECT 1 FROM locations l WHERE l.id = r.location_id)")
        conn.execute("DROP INDEX IF EXISTS idx_rolls_location")
        conn.execute("ALTER TABLE rolls DROP COLUMN location_id")
    # v0.5: user-visible roll number (auto = the row id, editable).
    if "roll_no" not in cols("rolls"):
        conn.execute("ALTER TABLE rolls ADD COLUMN roll_no TEXT NOT NULL DEFAULT ''")
        conn.execute("UPDATE rolls SET roll_no = CAST(id AS TEXT) WHERE roll_no = ''")
    # v0.6: optional lens per roll (lenses live on the cameras page).
    if "lens_id" not in cols("rolls"):
        conn.execute("ALTER TABLE rolls ADD COLUMN lens_id INTEGER")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_rolls_roll_no "
                 "ON rolls(roll_no)")


def init_db(conn):
    conn.executescript(SCHEMA)
    _migrate(conn)
    if conn.execute("SELECT COUNT(*) c FROM cameras").fetchone()["c"] == 0:
        ts = now()
        conn.executemany("INSERT INTO cameras(name, created_at) VALUES (?,?)",
                         [(n, ts) for n in SEED_CAMERAS])
    if conn.execute("SELECT COUNT(*) c FROM films").fetchone()["c"] == 0:
        ts = now()
        conn.executemany("INSERT INTO films(name, created_at) VALUES (?,?)",
                         [(n, ts) for n in SEED_FILMS])
    for k, v in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?,?)",
                     (k, v))
    conn.commit()


# ---------------------------------------------------------------- settings

def get_settings(conn):
    out = dict(DEFAULT_SETTINGS)
    for row in conn.execute("SELECT key, value FROM settings"):
        out[row["key"]] = row["value"]
    return out


def set_settings(conn, patch):
    for k, v in patch.items():
        conn.execute("INSERT INTO settings(key, value) VALUES(?,?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     (k, v))
    conn.commit()
    return get_settings(conn)


# ---------------------------------------------------------------- cameras

def list_cameras(conn):
    return [dict(r) for r in conn.execute(
        """SELECT c.id, c.name, COUNT(r.id) AS used_count,
                  MAX(COALESCE(r.shot_at, r.created_at)) AS last_used
           FROM cameras c LEFT JOIN rolls r ON r.camera_id = c.id
           GROUP BY c.id ORDER BY c.name""")]


def get_camera(conn, camera_id):
    return conn.execute("SELECT * FROM cameras WHERE id=?",
                        (camera_id,)).fetchone()


def get_roll(conn, roll_id):
    return conn.execute("SELECT * FROM rolls WHERE id=?",
                        (roll_id,)).fetchone()


def add_camera(conn, name):
    row = conn.execute("SELECT * FROM cameras WHERE name = ?", (name,)).fetchone()
    if row is None:
        cur = conn.execute("INSERT INTO cameras(name, created_at) VALUES (?,?)",
                           (name, now()))
        conn.commit()
        row = conn.execute("SELECT * FROM cameras WHERE id=?",
                           (cur.lastrowid,)).fetchone()
    return dict(row)


# ---------------------------------------------------------------- lenses

def list_lenses(conn):
    return [dict(r) for r in conn.execute(
        """SELECT l.id, l.name, COUNT(r.id) AS used_count,
                  MAX(COALESCE(r.shot_at, r.created_at)) AS last_used
           FROM lenses l LEFT JOIN rolls r ON r.lens_id = l.id
           GROUP BY l.id ORDER BY l.name""")]


def get_lens(conn, lens_id):
    row = conn.execute("SELECT * FROM lenses WHERE id=?",
                       (lens_id,)).fetchone()
    return dict(row) if row else None


def add_lens(conn, name):
    row = conn.execute("SELECT * FROM lenses WHERE name = ?", (name,)).fetchone()
    if row is None:
        cur = conn.execute("INSERT INTO lenses(name, created_at) VALUES (?,?)",
                           (name, now()))
        conn.commit()
        row = conn.execute("SELECT * FROM lenses WHERE id=?",
                           (cur.lastrowid,)).fetchone()
    return dict(row)


# ---------------------------------------------------------------- films

def list_films(conn):
    return [dict(r) for r in conn.execute(
        """SELECT f.id, f.name, COUNT(r.id) AS used_count,
                  MAX(COALESCE(r.shot_at, r.created_at)) AS last_used
           FROM films f LEFT JOIN rolls r ON r.film_id = f.id
           GROUP BY f.id ORDER BY f.name""")]


def get_film(conn, film_id):
    return conn.execute("SELECT * FROM films WHERE id=?", (film_id,)).fetchone()


def add_film(conn, name):
    row = conn.execute("SELECT * FROM films WHERE name = ?", (name,)).fetchone()
    if row is None:
        cur = conn.execute("INSERT INTO films(name, created_at) VALUES (?,?)",
                           (name, now()))
        conn.commit()
        row = conn.execute("SELECT * FROM films WHERE id=?",
                           (cur.lastrowid,)).fetchone()
    return dict(row)


# ---------------------------------------------------------------- locations

def list_locations(conn):
    """Locations newest visit first, each with its rolls (newest visit first).

    The roll list comes from the roll_locations junction; rl.note is the
    note for THAT roll at THAT place (set in the New Location popover).
    """
    out = []
    for loc in conn.execute(
            "SELECT * FROM locations ORDER BY visited_at DESC, id DESC"):
        rolls = [dict(r) for r in conn.execute(
            """SELECT r.id, r.roll_no, r.shot_at, rl.note, rl.visited_at,
                      c.name AS camera, f.name AS film
               FROM roll_locations rl
               JOIN rolls   r ON r.id = rl.roll_id
               JOIN cameras c ON c.id = r.camera_id
               JOIN films   f ON f.id = r.film_id
               WHERE rl.location_id = ?
               ORDER BY rl.visited_at DESC, r.id DESC""",
            (loc["id"],))]
        d = dict(loc)
        d["rolls"] = rolls
        out.append(d)
    return out


def get_location(conn, location_id):
    return conn.execute("SELECT * FROM locations WHERE id=?",
                        (location_id,)).fetchone()


def add_location(conn, name, note="", lat=None, lon=None, visited_at=None):
    cur = conn.execute(
        "INSERT INTO locations(name, note, lat, lon, visited_at, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (name, note, lat, lon, visited_at or now_local(), now()))
    conn.commit()
    return dict(conn.execute("SELECT * FROM locations WHERE id=?",
                             (cur.lastrowid,)).fetchone())


def find_location_by_name(conn, name):
    return conn.execute("SELECT * FROM locations WHERE name = ? COLLATE NOCASE",
                        (name,)).fetchone()


def get_or_create_location(conn, name, lat=None, lon=None, visited_at=None):
    """Match an existing location by name (case-insensitive), else create."""
    row = find_location_by_name(conn, name)
    if row is not None:
        return dict(row)
    return add_location(conn, name, "", lat, lon, visited_at)


def touch_location_visit(conn, location_id, visited_at):
    """A visit refreshes the location's date (only ever moves forward)."""
    conn.execute("UPDATE locations SET visited_at=? WHERE id=? AND visited_at<=?",
                 (visited_at, location_id, visited_at))


def set_location_note(conn, location_id, note):
    """Standalone location note (only when the location has no note yet)."""
    if note:
        conn.execute("UPDATE locations SET note=? WHERE id=? AND note=''",
                     (note, location_id))


def attach_location(conn, roll_id, location_id, note="", visited_at=None):
    """Link a location to a roll (the New Location popover path).

    Re-adding the same place to the same roll updates the entry instead of
    duplicating it; a blank note never erases an existing one. visited_at
    defaults to the roll's shot date.
    """
    roll = conn.execute("SELECT shot_at FROM rolls WHERE id=?",
                        (roll_id,)).fetchone()
    if roll is None:
        raise ValueError("unknown roll_id")
    if conn.execute("SELECT 1 FROM locations WHERE id=?",
                    (location_id,)).fetchone() is None:
        raise ValueError("unknown location_id")
    visited = visited_at or roll["shot_at"] or now_local()
    conn.execute(
        "INSERT INTO roll_locations(roll_id, location_id, note, visited_at) "
        "VALUES (?,?,?,?) "
        "ON CONFLICT(roll_id, location_id) DO UPDATE SET "
        "note=CASE WHEN excluded.note != '' THEN excluded.note ELSE note END, "
        "visited_at=excluded.visited_at",
        (roll_id, location_id, note, visited))
    touch_location_visit(conn, location_id, visited)
    conn.commit()


# ---------------------------------------------------------------- rolls

def list_rolls(conn):
    """Rolls newest shot first, each with its locations (newest visit first).

    Each roll carries a locations list: {id, name, note, visited_at} where
    note is the roll-at-that-place note.
    """
    rolls = [dict(r) for r in conn.execute(
        """SELECT r.id, r.roll_no, r.note, r.shot_at, r.created_at,
                  r.camera_id, r.film_id, r.lens_id,
                  c.name AS camera, f.name AS film, le.name AS lens
           FROM rolls r
           JOIN cameras c ON c.id = r.camera_id
           JOIN films   f ON f.id = r.film_id
           LEFT JOIN lenses le ON le.id = r.lens_id
           ORDER BY r.shot_at DESC, r.id DESC""")]
    for r in rolls:
        r["locations"] = [dict(x) for x in conn.execute(
            """SELECT l.id, l.name, l.lat, l.lon, rl.note, rl.visited_at
               FROM roll_locations rl
               JOIN locations l ON l.id = rl.location_id
               WHERE rl.roll_id = ?
               ORDER BY rl.visited_at DESC, l.name""", (r["id"],))]
    return rolls


def add_roll(conn, camera_id, film_id, location_id, note="", shot_at=None,
             roll_no=None, lens_id=None):
    """Create a roll and link its first location (New Roll popover).

    roll_no is the user-visible number; blank/None means auto (the row id,
    so numbering continues on its own). Uniqueness is enforced by a UNIQUE
    index plus a friendly pre-check in the web layer.
    """
    shot_at = shot_at or now_local()
    if conn.execute("SELECT 1 FROM locations WHERE id=?",
                    (location_id,)).fetchone() is None:
        raise ValueError("unknown location_id")
    cur = conn.execute(
        "INSERT INTO rolls(roll_no, camera_id, film_id, lens_id, note, "
        "shot_at, created_at) VALUES (?,?,?,?,?,?,?)",
        (roll_no or "", camera_id, film_id, lens_id, note, shot_at, now()))
    roll_id = cur.lastrowid
    if not roll_no:
        conn.execute("UPDATE rolls SET roll_no=? WHERE id=?",
                     (str(roll_id), roll_id))
    conn.execute(
        "INSERT INTO roll_locations(roll_id, location_id, note, visited_at) "
        "VALUES (?,?,?,?)", (roll_id, location_id, "", shot_at))
    touch_location_visit(conn, location_id, shot_at)
    conn.commit()
    roll = dict(conn.execute("SELECT * FROM rolls WHERE id=?",
                             (roll_id,)).fetchone())
    roll["locations"] = [dict(conn.execute(
        "SELECT l.id, l.name, rl.note, rl.visited_at "
        "FROM roll_locations rl JOIN locations l ON l.id = rl.location_id "
        "WHERE rl.roll_id=? AND rl.location_id=?",
        (roll_id, location_id)).fetchone())]
    return roll


def current_roll(conn):
    """The most recent roll with its camera/film names, or None.

    Used by the New Location popover to show (read-only) the current
    camera and roll.
    """
    row = conn.execute(
        """SELECT r.id, r.roll_no, r.shot_at, c.name AS camera, f.name AS film
           FROM rolls r
           JOIN cameras c ON c.id = r.camera_id
           JOIN films   f ON f.id = r.film_id
           ORDER BY r.shot_at DESC, r.id DESC LIMIT 1""").fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------- editing
#
# Whitelisted updates only: keys are fixed by code, never by the client.

def _apply_update(conn, table, id_col, id_val, patch):
    if not patch:
        return None
    sets = ", ".join(f"{k}=?" for k in patch)
    conn.execute(f"UPDATE {table} SET {sets} WHERE {id_col}=?",
                 (*patch.values(), id_val))
    conn.commit()
    return dict(conn.execute(
        f"SELECT * FROM {table} WHERE {id_col}=?", (id_val,)).fetchone())


def update_roll(conn, roll_id, patch):
    """patch keys: camera_id, film_id, note, shot_at, roll_no (validated)."""
    return _apply_update(conn, "rolls", "id", roll_id, patch)


def roll_no_taken(conn, roll_no, exclude_id=None):
    row = conn.execute(
        "SELECT id FROM rolls WHERE roll_no=? AND id != ?",
        (roll_no, exclude_id or -1)).fetchone()
    return row is not None


def update_location(conn, location_id, patch):
    """patch keys: name, note, visited_at."""
    return _apply_update(conn, "locations", "id", location_id, patch)


def update_roll_location(conn, roll_id, location_id, patch):
    """Edit one roll-at-place entry: patch keys note, visited_at."""
    row = conn.execute(
        "SELECT 1 FROM roll_locations WHERE roll_id=? AND location_id=?",
        (roll_id, location_id)).fetchone()
    if row is None:
        return None
    if patch:
        sets = ", ".join(f"{k}=?" for k in patch)
        conn.execute(f"UPDATE roll_locations SET {sets} "
                     "WHERE roll_id=? AND location_id=?",
                     (*patch.values(), roll_id, location_id))
        conn.commit()
    if "visited_at" in patch:
        touch_location_visit(conn, location_id, patch["visited_at"])
        conn.commit()
    return _entry_row(conn, roll_id, location_id)


def _entry_row(conn, roll_id, location_id):
    return dict(conn.execute(
        "SELECT rl.note, rl.visited_at, l.id, l.name, l.lat, l.lon "
        "FROM roll_locations rl JOIN locations l ON l.id = rl.location_id "
        "WHERE rl.roll_id=? AND rl.location_id=?",
        (roll_id, location_id)).fetchone())


def relink_roll_location(conn, roll_id, from_location_id, to_location_id):
    """Move a roll-at-place entry to another location (change the place a
    roll was shot at). If the roll already lists the target, the edited
    entry merges into it (its note fills a blank target note).
    """
    src = conn.execute(
        "SELECT note, visited_at FROM roll_locations "
        "WHERE roll_id=? AND location_id=?",
        (roll_id, from_location_id)).fetchone()
    if src is None:
        return None
    if from_location_id == to_location_id:
        return _entry_row(conn, roll_id, to_location_id)
    tgt = conn.execute(
        "SELECT note FROM roll_locations "
        "WHERE roll_id=? AND location_id=?",
        (roll_id, to_location_id)).fetchone()
    if tgt is None:
        conn.execute(
            "UPDATE roll_locations SET location_id=? "
            "WHERE roll_id=? AND location_id=?",
            (to_location_id, roll_id, from_location_id))
    else:
        conn.execute(
            "UPDATE roll_locations SET note=CASE WHEN note='' THEN ? ELSE note END "
            "WHERE roll_id=? AND location_id=?",
            (src["note"], roll_id, to_location_id))
        conn.execute(
            "DELETE FROM roll_locations WHERE roll_id=? AND location_id=?",
            (roll_id, from_location_id))
    conn.commit()
    return _entry_row(conn, roll_id, to_location_id)


def delete_roll(conn, roll_id):
    """Delete a roll and its location entries. Rolls go whenever."""
    if conn.execute("SELECT 1 FROM rolls WHERE id=?", (roll_id,)).fetchone() is None:
        return False
    conn.execute("DELETE FROM roll_locations WHERE roll_id=?", (roll_id,))
    conn.execute("DELETE FROM rolls WHERE id=?", (roll_id,))
    conn.commit()
    return True


def delete_location(conn, location_id):
    """Delete a location only when no rolls reference it; else False."""
    if conn.execute("SELECT 1 FROM locations WHERE id=?",
                    (location_id,)).fetchone() is None:
        return False
    if conn.execute("SELECT 1 FROM roll_locations WHERE location_id=?",
                    (location_id,)).fetchone() is not None:
        return False
    conn.execute("DELETE FROM locations WHERE id=?", (location_id,))
    conn.commit()
    return True

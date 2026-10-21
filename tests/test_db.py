"""Hermetic DB tests: seeding, CRUD, MRU data, current roll, settings,
shot/visit dates, roll numbers, migration."""
import sqlite3

from filmnotes import db


def test_seed_cameras(conn):
    names = [c["name"] for c in db.list_cameras(conn)]
    assert names == sorted(db.SEED_CAMERAS)
    assert set(db.SEED_CAMERAS) == {
        "Leica MP", "Leica M6", "Canon 1V", "Pentax 67", "Bronica SQ-A",
        "Pentax 645N2"}


def test_seed_films(conn):
    names = set(f["name"] for f in db.list_films(conn))
    assert names == {
        "Fujifilm Provia 100", "Fujifilm Velvia 50", "Fujifilm Velvia 100",
        "Kodak Portra 160", "Kodak Portra 400", "Kodak Portra 800",
        "Ilford Delta 100", "Ilford Delta 400", "Ilford XP2 400",
        "Ilford HP5 400", "Kodak Tri-X 400", "Kodak T-Max 100",
        "Kodak T-Max 400", "Kodak T-Max 3200", "Fujifilm Acros II"}


def test_seed_is_idempotent(conn):
    db.init_db(conn)  # second run must not duplicate or wipe
    assert len(db.list_cameras(conn)) == len(db.SEED_CAMERAS)
    assert len(db.list_films(conn)) == len(db.SEED_FILMS)


def test_default_settings(conn):
    assert db.get_settings(conn)["theme"] == "auto"


def test_set_settings(conn):
    s = db.set_settings(conn, {"theme": "dark"})
    assert s["theme"] == "dark"
    assert db.get_settings(conn)["theme"] == "dark"


def test_add_camera_dedupe(conn):
    a = db.add_camera(conn, "Hasselblad 500C/M")
    b = db.add_camera(conn, "Hasselblad 500C/M")
    assert a["id"] == b["id"]


def test_add_roll_and_listing(conn):
    cam = db.list_cameras(conn)[0]["id"]
    film = db.list_films(conn)[0]["id"]
    loc = db.add_location(conn, "Golden Gate Park")
    roll = db.add_roll(conn, cam, film, loc["id"], "f/8 sunny")
    rolls = db.list_rolls(conn)
    assert rolls[0]["id"] == roll["id"]
    assert rolls[0]["roll_no"] == str(roll["id"])   # auto = row id
    assert rolls[0]["locations"][0]["name"] == "Golden Gate Park"
    assert rolls[0]["note"] == "f/8 sunny"
    assert rolls[0]["camera"] and rolls[0]["film"]


def test_custom_roll_numbers(conn):
    cam = db.list_cameras(conn)[0]["id"]
    film = db.list_films(conn)[0]["id"]
    loc = db.add_location(conn, "Home")
    a = db.add_roll(conn, cam, film, loc["id"], roll_no="12A")
    b = db.add_roll(conn, cam, film, loc["id"])      # auto continues
    assert a["roll_no"] == "12A"
    assert b["roll_no"] == str(b["id"])
    # renumber old rolls
    db.update_roll(conn, b["id"], {"roll_no": "7"})
    nos = sorted(r["roll_no"] for r in db.list_rolls(conn))
    assert nos == ["12A", "7"]
    assert db.roll_no_taken(conn, "12A")
    assert not db.roll_no_taken(conn, "12A", exclude_id=a["id"])
    assert not db.roll_no_taken(conn, "999")


def test_roll_no_unique_index(conn):
    cam = db.list_cameras(conn)[0]["id"]
    film = db.list_films(conn)[0]["id"]
    loc = db.add_location(conn, "Home")
    db.add_roll(conn, cam, film, loc["id"], roll_no="X1")
    import pytest
    with pytest.raises(sqlite3.IntegrityError):
        db.add_roll(conn, cam, film, loc["id"], roll_no="X1")


def test_migrate_backfills_roll_no(conn):
    cam = db.list_cameras(conn)[0]["id"]
    film = db.list_films(conn)[0]["id"]
    loc = db.add_location(conn, "Legacy")
    roll = db.add_roll(conn, cam, film, loc["id"])
    conn.execute("DROP INDEX IF EXISTS idx_rolls_roll_no")
    conn.execute("ALTER TABLE rolls DROP COLUMN roll_no")
    db.init_db(conn)
    r = db.list_rolls(conn)[0]
    assert r["roll_no"] == str(roll["id"])


def test_roll_accumulates_locations(conn):
    cam = db.list_cameras(conn)[0]["id"]
    film = db.list_films(conn)[0]["id"]
    a = db.add_location(conn, "Ken Willhans")
    roll = db.add_roll(conn, cam, film, a["id"], shot_at="2026-01-01 10:00")
    b = db.add_location(conn, "Belfountain")
    db.attach_location(conn, roll["id"], b["id"], "last 2 frames")
    r = db.list_rolls(conn)[0]
    names = {l["name"] for l in r["locations"]}
    assert names == {"Ken Willhans", "Belfountain"}
    belf = [l for l in r["locations"] if l["name"] == "Belfountain"][0]
    assert belf["note"] == "last 2 frames"
    assert belf["visited_at"] == "2026-01-01 10:00"  # defaults to shot date
    # the location page lists the roll under it, with the entry note
    locs = {l["name"]: l for l in db.list_locations(conn)}
    assert locs["Belfountain"]["rolls"][0]["id"] == roll["id"]
    assert locs["Belfountain"]["rolls"][0]["note"] == "last 2 frames"


def test_attach_updates_in_place(conn):
    cam = db.list_cameras(conn)[0]["id"]
    film = db.list_films(conn)[0]["id"]
    a = db.add_location(conn, "Tops")
    roll = db.add_roll(conn, cam, film, a["id"])
    db.attach_location(conn, roll["id"], a["id"], "first note")
    db.attach_location(conn, roll["id"], a["id"], "")      # blank keeps note
    r = db.list_rolls(conn)[0]
    assert len(r["locations"]) == 1
    assert r["locations"][0]["note"] == "first note"
    db.attach_location(conn, roll["id"], a["id"], "new note")
    r = db.list_rolls(conn)[0]
    assert len(r["locations"]) == 1
    assert r["locations"][0]["note"] == "new note"


def test_attach_rejects_unknown_ids(conn):
    cam = db.list_cameras(conn)[0]["id"]
    film = db.list_films(conn)[0]["id"]
    a = db.add_location(conn, "Nowhere")
    roll = db.add_roll(conn, cam, film, a["id"])
    import pytest
    with pytest.raises(ValueError):
        db.attach_location(conn, roll["id"], 99999)
    with pytest.raises(ValueError):
        db.attach_location(conn, 99999, a["id"])
    with pytest.raises(ValueError):
        db.add_roll(conn, cam, film, 99999)


def test_migrate_from_single_location_schema(conn):
    # simulate the pre-junction schema: re-add rolls.location_id with data
    cam = db.list_cameras(conn)[0]["id"]
    film = db.list_films(conn)[0]["id"]
    a = db.add_location(conn, "One")
    b = db.add_location(conn, "Two")
    db.add_roll(conn, cam, film, a["id"], shot_at="2025-05-05 05:05")
    conn.execute("ALTER TABLE rolls ADD COLUMN location_id INTEGER")
    conn.execute("UPDATE rolls SET location_id = ?", (a["id"],))
    db.init_db(conn)  # backfills the junction, drops the column
    assert "location_id" not in [r["name"] for r in
                                 conn.execute("PRAGMA table_info(rolls)")]
    r = db.list_rolls(conn)[0]
    assert r["locations"][0]["name"] == "One"
    assert r["locations"][0]["visited_at"] == "2025-05-05 05:05"
    locs = {l["name"]: l for l in db.list_locations(conn)}
    assert len(locs["One"]["rolls"]) == 1
    assert len(locs["Two"]["rolls"]) == 0


def test_locations_page_groups_rolls(conn):
    cam = db.list_cameras(conn)[0]["id"]
    film = db.list_films(conn)[0]["id"]
    a = db.add_location(conn, "Battery Spencer")
    b = db.add_location(conn, "Point Reyes")
    db.add_roll(conn, cam, film, a["id"])
    db.add_roll(conn, cam, film, a["id"])
    db.add_roll(conn, cam, film, b["id"])
    locs = {l["name"]: l for l in db.list_locations(conn)}
    assert len(locs["Battery Spencer"]["rolls"]) == 2
    assert len(locs["Point Reyes"]["rolls"]) == 1
    r = locs["Battery Spencer"]["rolls"][0]
    assert r["camera"] and r["film"] and r["shot_at"]


def test_mru_fields(conn):
    cams = {c["name"]: c for c in db.list_cameras(conn)}
    films = {f["name"]: f for f in db.list_films(conn)}
    loc = db.add_location(conn, "Home")
    db.add_roll(conn, cams["Leica MP"]["id"], films["Kodak Portra 400"]["id"],
                loc["id"])
    cams = {c["name"]: c for c in db.list_cameras(conn)}
    films = {f["name"]: f for f in db.list_films(conn)}
    assert cams["Leica MP"]["used_count"] == 1
    assert cams["Leica MP"]["last_used"] is not None
    assert cams["Leica M6"]["used_count"] == 0
    assert cams["Leica M6"]["last_used"] is None
    assert films["Kodak Portra 400"]["last_used"] is not None


def test_get_or_create_location_matches_case_insensitive(conn):
    a = db.get_or_create_location(conn, "Golden Gate Park")
    b = db.get_or_create_location(conn, "golden gate park", 37.7, -122.5)
    assert a["id"] == b["id"]
    assert b["lat"] is None  # existing match keeps original coords


def test_get_or_create_location_new_stores_coords(conn):
    loc = db.get_or_create_location(conn, "Presidio", 37.8, -122.4)
    assert loc["lat"] == 37.8 and loc["lon"] == -122.4


def test_current_roll_is_newest(conn):
    assert db.current_roll(conn) is None
    cam = db.list_cameras(conn)[0]["id"]
    film = db.list_films(conn)[0]["id"]
    loc = db.add_location(conn, "Yosemite")
    db.add_roll(conn, cam, film, loc["id"])
    cam2 = db.list_cameras(conn)[1]["id"]
    newer = db.add_roll(conn, cam2, film, loc["id"])
    cur = db.current_roll(conn)
    assert cur["id"] == newer["id"]
    assert cur["camera"] == "Canon 1V"  # list_cameras[1] is alphabetical


# ------------------------------------------------------- shot / visit dates

def _ids(rows):
    return [r["id"] for r in rows]


def test_add_roll_defaults_shot_at_now(conn):
    cam, film = db.list_cameras(conn)[0]["id"], db.list_films(conn)[0]["id"]
    loc = db.add_location(conn, "Home")
    roll = db.add_roll(conn, cam, film, loc["id"])
    assert len(roll["shot_at"]) == 16 and roll["shot_at"][4] == "-" \
        and roll["shot_at"][10] == " "


def test_rolls_sort_by_shot_at_not_creation(conn):
    cam, film = db.list_cameras(conn)[0]["id"], db.list_films(conn)[0]["id"]
    loc = db.add_location(conn, "Home")
    recent = db.add_roll(conn, cam, film, loc["id"],
                         shot_at="2024-06-01 09:00")
    old = db.add_roll(conn, cam, film, loc["id"], shot_at="2020-01-01 10:00")
    assert _ids(db.list_rolls(conn)) == [recent["id"], old["id"]]


def test_locations_sort_by_visited_at_and_roll_touch_refreshes(conn):
    cam, film = db.list_cameras(conn)[0]["id"], db.list_films(conn)[0]["id"]
    old_loc = db.add_location(conn, "Old Place", visited_at="2019-01-01 12:00")
    new_loc = db.add_location(conn, "New Place", visited_at="2024-01-01 12:00")
    names = [l["name"] for l in db.list_locations(conn)]
    assert names == ["New Place", "Old Place"]
    # a roll shot long ago in Old Place must NOT drag its visited date back
    db.add_roll(conn, cam, film, old_loc["id"], shot_at="2018-05-05 08:00")
    locs = {l["name"]: l for l in db.list_locations(conn)}
    assert locs["Old Place"]["visited_at"] == "2019-01-01 12:00"
    # ...but a newer roll moves it forward
    db.add_roll(conn, cam, film, old_loc["id"], shot_at="2025-02-02 08:00")
    locs = {l["name"]: l for l in db.list_locations(conn)}
    assert locs["Old Place"]["visited_at"] == "2025-02-02 08:00"
    assert [l["name"] for l in db.list_locations(conn)][0] == "Old Place"


def test_rolls_under_location_sort_by_shot_at(conn):
    cam, film = db.list_cameras(conn)[0]["id"], db.list_films(conn)[0]["id"]
    loc = db.add_location(conn, "Beach")
    db.add_roll(conn, cam, film, loc["id"], shot_at="2024-01-01 09:00")
    newer = db.add_roll(conn, cam, film, loc["id"], shot_at="2024-06-01 09:00")
    locs = {l["name"]: l for l in db.list_locations(conn)}
    assert locs["Beach"]["rolls"][0]["id"] == newer["id"]


def test_mru_last_used_follows_shot_at(conn):
    cam = db.list_cameras(conn)[0]["id"]
    film = db.list_films(conn)[0]["id"]
    loc = db.add_location(conn, "Home")
    db.add_roll(conn, cam, film, loc["id"], shot_at="2030-01-01 00:00")
    cams = {c["name"]: c for c in db.list_cameras(conn)}
    assert cams[[c["name"] for c in db.list_cameras(conn)][0]]["last_used"] \
        == "2030-01-01 00:00"


def test_current_roll_by_shot_at(conn):
    cam, film = db.list_cameras(conn)[0]["id"], db.list_films(conn)[0]["id"]
    loc = db.add_location(conn, "Home")
    db.add_roll(conn, cam, film, loc["id"], shot_at="2020-01-01 10:00")
    newest = db.add_roll(conn, cam, film, loc["id"], shot_at="2024-01-01 10:00")
    assert db.current_roll(conn)["id"] == newest["id"]


def test_migrate_backfills_dates_on_old_schema(conn):
    cam, film = db.list_cameras(conn)[0]["id"], db.list_films(conn)[0]["id"]
    loc = db.add_location(conn, "Legacy")
    roll = db.add_roll(conn, cam, film, loc["id"])
    # simulate a pre-feature database
    conn.execute("ALTER TABLE rolls DROP COLUMN shot_at")
    conn.execute("ALTER TABLE locations DROP COLUMN visited_at")
    db.init_db(conn)  # must re-add the columns and backfill from created_at
    r = db.list_rolls(conn)[0]
    assert r["shot_at"] == roll["created_at"][:16].replace("T", " ")
    assert db.list_locations(conn)[0]["visited_at"] == \
        loc["created_at"][:16].replace("T", " ")


def test_delete_roll_and_location_rules(conn):
    cam = db.list_cameras(conn)[0]["id"]
    film = db.list_films(conn)[0]["id"]
    loc = db.add_location(conn, "Creek")
    roll = db.add_roll(conn, cam, film, loc["id"])
    assert db.delete_location(conn, loc["id"]) is False   # still in use
    assert db.delete_roll(conn, roll["id"]) is True
    assert db.delete_roll(conn, roll["id"]) is False      # already gone
    assert db.list_rolls(conn) == []
    assert db.delete_location(conn, loc["id"]) is True    # now free
    assert db.delete_location(conn, loc["id"]) is False   # already gone
    assert db.list_locations(conn) == []


def test_relink_merges_duplicate_entries(conn):
    cam = db.list_cameras(conn)[0]["id"]
    film = db.list_films(conn)[0]["id"]
    a = db.add_location(conn, "Alpha")
    b = db.add_location(conn, "Beta")
    roll = db.add_roll(conn, cam, film, a["id"])
    db.attach_location(conn, roll["id"], b["id"], "beta note")
    # moving Alpha-entry onto Beta merges: one entry, blank note filled
    entry = db.relink_roll_location(conn, roll["id"], a["id"], b["id"])
    assert entry["name"] == "Beta"
    r = db.list_rolls(conn)[0]
    assert [l["name"] for l in r["locations"]] == ["Beta"]
    assert r["locations"][0]["note"] == "beta note"
    # relinking a non-existent entry returns None
    assert db.relink_roll_location(conn, roll["id"], a["id"], b["id"]) is None


# ------------------------------------------------------------------ lenses

def test_lenses_crud_and_usage(conn):
    a = db.add_lens(conn, "50mm f/1.4")
    b = db.add_lens(conn, "50mm f/1.4")           # idempotent by name
    assert a["id"] == b["id"]
    db.add_lens(conn, "90mm f/2")
    names = [l["name"] for l in db.list_lenses(conn)]
    assert names == ["50mm f/1.4", "90mm f/2"]
    cam = db.list_cameras(conn)[0]["id"]
    film = db.list_films(conn)[0]["id"]
    loc = db.add_location(conn, "Home")
    db.add_roll(conn, cam, film, loc["id"], lens_id=a["id"])
    stats = {l["name"]: l for l in db.list_lenses(conn)}
    assert stats["50mm f/1.4"]["used_count"] == 1
    assert stats["90mm f/2"]["used_count"] == 0
    assert db.get_lens(conn, a["id"])["name"] == "50mm f/1.4"
    assert db.get_lens(conn, 99999) is None


def test_roll_lens_optional_and_clearable(conn):
    cam = db.list_cameras(conn)[0]["id"]
    film = db.list_films(conn)[0]["id"]
    loc = db.add_location(conn, "Home")
    lens = db.add_lens(conn, "35mm f/2")
    r = db.add_roll(conn, cam, film, loc["id"])   # lens optional
    assert r["lens_id"] is None
    db.update_roll(conn, r["id"], {"lens_id": lens["id"]})
    assert db.list_rolls(conn)[0]["lens"] == "35mm f/2"
    db.update_roll(conn, r["id"], {"lens_id": None})
    assert db.list_rolls(conn)[0]["lens_id"] is None


def test_migrate_adds_lens_id(conn):
    conn.execute("DROP INDEX IF EXISTS idx_rolls_roll_no")
    conn.execute("ALTER TABLE rolls DROP COLUMN lens_id")
    db.init_db(conn)
    assert db.list_rolls(conn) is not None        # column back in place


def test_lens_compatibility(conn):
    lens = db.add_lens(conn, "50mm f/1.4")
    cam1 = db.list_cameras(conn)[0]["id"]
    cam2 = db.list_cameras(conn)[1]["id"]
    assert lens["camera_ids"] == []               # unassigned = all cameras
    lens = db.set_lens_cameras(conn, lens["id"], [cam1, cam2, cam1])
    assert sorted(lens["camera_ids"]) == sorted([cam1, cam2])   # deduped
    assert db.list_lenses(conn)[0]["camera_ids"] == lens["camera_ids"]
    lens = db.set_lens_cameras(conn, lens["id"], [])            # back to all
    assert lens["camera_ids"] == []
    import pytest
    with pytest.raises(ValueError):
        db.set_lens_cameras(conn, lens["id"], [99999])
    assert db.set_lens_cameras(conn, 99999, []) is None


def test_inventory_fields_cameras_lenses(conn):
    cam = db.list_cameras(conn)[0]
    assert cam["serial"] == "" and cam["note"] == ""
    out = db.update_camera(conn, cam["id"], {"serial": "12345", "note": "reclad"})
    assert out["serial"] == "12345" and out["note"] == "reclad"
    assert db.update_camera(conn, 99999, {"serial": "x"}) is None
    lens = db.add_lens(conn, "50mm")
    out = db.update_lens(conn, lens["id"], {"serial": "L1", "note": "haze"})
    assert out["serial"] == "L1" and out["note"] == "haze"
    assert db.update_lens(conn, 99999, {"serial": "x"}) is None


def test_migrate_adds_inventory_cols(conn):
    for table in ("cameras", "lenses"):
        cols = {r["name"] for r in conn.execute(
            f"PRAGMA table_info({table})")}
        for col in ("serial", "note"):
            conn.execute(f"ALTER TABLE {table} DROP COLUMN {col}")
    db.init_db(conn)
    for table in ("cameras", "lenses"):
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        assert {"serial", "note"} <= cols

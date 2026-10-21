"""Flask app. Thin routes only, no SQL (all SQL lives in db.py).

/api/* errors are always JSON, never an HTML 500. Input hygiene: _body()
requires a JSON object (400 otherwise); _str()/_num() coerce and bound.
"""
import os
from datetime import datetime

from flask import Flask, jsonify, render_template, request

from . import __version__, db

MAX_NAME = 120
MAX_NOTE = 5000
THEMES = ("auto", "light", "dark")


def _body():
    """Return the request JSON object or raise a 400 (returned as JSON)."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise BadRequest("expected a JSON object body")
    return data


class BadRequest(Exception):
    def __init__(self, msg):
        super().__init__(msg)
        self.msg = msg


def _str(data, key, required=False, max_len=MAX_NAME, default=""):
    v = data.get(key, default)
    if v is None:
        v = ""
    if not isinstance(v, str):
        raise BadRequest(f"{key} must be a string")
    v = v.strip()
    if required and not v:
        raise BadRequest(f"{key} is required")
    if len(v) > max_len:
        raise BadRequest(f"{key} too long (max {max_len})")
    return v


def _note(data, key="note"):
    return _str(data, key, max_len=MAX_NOTE)


def _datetime(data, key):
    """Optional 'YYYY-MM-DD HH:MM' (T separator tolerated, optional :SS).

    Normalized to 'YYYY-MM-DD HH:MM' (fixed width -> string-sortable).
    Returns None when absent/empty.
    """
    v = data.get(key)
    if v is None or v == "":
        return None
    if not isinstance(v, str):
        raise BadRequest(f"{key} must be a string")
    v = v.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(v, fmt).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            pass
    raise BadRequest(f"{key} must look like YYYY-MM-DD HH:MM")


def _num(data, key):
    v = data.get(key)
    if v is None or v == "":
        return None
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        raise BadRequest(f"{key} must be a number")
    if key == "lat" and not (-90 <= v <= 90):
        raise BadRequest("lat out of range")
    if key == "lon" and not (-180 <= v <= 180):
        raise BadRequest("lon out of range")
    return float(v)


def create_app(db_path, conn=None):
    root = os.path.dirname(os.path.abspath(__file__))
    app = Flask(__name__, root_path=root,
                template_folder="templates", static_folder="static")
    app.config["JSON_SORT_KEYS"] = False
    if conn is None:
        conn = db.connect(db_path)
    db.init_db(conn)

    @app.errorhandler(BadRequest)
    def _bad(e):
        return jsonify(error=e.msg), 400

    @app.errorhandler(404)
    def _nf(e):
        if request.path.startswith("/api/"):
            return jsonify(error="not found"), 404
        return e

    @app.errorhandler(500)
    def _500(e):
        return jsonify(error="internal error"), 500

    # ------------------------------------------------------------ pages

    @app.route("/")
    def index():
        return render_template("index.html",
                               app_version=__version__,
                               settings=db.get_settings(conn))

    # ------------------------------------------------------------ rolls

    @app.get("/api/rolls")
    def api_rolls():
        return jsonify(db.list_rolls(conn))

    @app.post("/api/rolls")
    def api_new_roll():
        data = _body()
        for k in ("camera_id", "film_id"):
            if not isinstance(data.get(k), int) or isinstance(data.get(k), bool):
                raise BadRequest(f"{k} must be an integer")
        if db.get_camera(conn, data["camera_id"]) is None:
            raise BadRequest("unknown camera_id")
        if db.get_film(conn, data["film_id"]) is None:
            raise BadRequest("unknown film_id")
        note = _note(data)
        shot_at = _datetime(data, "shot_at")
        roll_no = _str(data, "roll_no", max_len=20)
        if roll_no and db.roll_no_taken(conn, roll_no):
            raise BadRequest("that roll number is already in use")
        if data.get("location_id") is not None:
            loc = db.get_location(conn, data["location_id"])
            if loc is None:
                raise BadRequest("unknown location_id")
            loc = dict(loc)
        else:
            name = _str(data, "location_name", required=True)
            loc = db.get_or_create_location(
                conn, name, _num(data, "lat"), _num(data, "lon"), shot_at)
        roll = db.add_roll(conn, data["camera_id"], data["film_id"],
                           loc["id"], note, shot_at, roll_no or None)
        return jsonify(roll), 201

    # ------------------------------------------------------------ locations

    @app.get("/api/locations")
    def api_locations():
        return jsonify(db.list_locations(conn))

    @app.get("/api/locations/current")
    def api_current():
        return jsonify(current=db.current_roll(conn))

    @app.post("/api/locations")
    def api_new_location():
        """Create/find a place and ATTACH it to the current roll (the one
        the popover shows). With no rolls yet it stays standalone and the
        note lands on the location itself.
        """
        data = _body()
        name = _str(data, "name", required=True)
        note = _note(data)
        visited_at = _datetime(data, "visited_at")
        lat, lon = _num(data, "lat"), _num(data, "lon")
        if (lat is None) != (lon is None):
            raise BadRequest("lat and lon must come together")
        loc = db.get_or_create_location(conn, name, lat, lon, visited_at)
        cur = db.current_roll(conn)
        attached = None
        if cur is not None:
            db.attach_location(conn, cur["id"], loc["id"], note, visited_at)
            attached = cur["id"]
        else:
            db.set_location_note(conn, loc["id"], note)
            conn.commit()
        loc = dict(db.get_location(conn, loc["id"]))
        loc["attached_to_roll"] = attached
        loc["attached_to_roll_no"] = cur["roll_no"] if attached else None
        return jsonify(loc), 201

    # ------------------------------------------------------------ cameras

    @app.get("/api/cameras")
    def api_cameras():
        return jsonify(db.list_cameras(conn))

    @app.post("/api/cameras")
    def api_new_camera():
        data = _body()
        name = _str(data, "name", required=True)
        return jsonify(db.add_camera(conn, name)), 201

    # ------------------------------------------------------------ films

    @app.get("/api/films")
    def api_films():
        return jsonify(db.list_films(conn))

    @app.post("/api/films")
    def api_new_film():
        data = _body()
        name = _str(data, "name", required=True)
        return jsonify(db.add_film(conn, name)), 201

    # ------------------------------------------------------------ editing

    @app.put("/api/rolls/<int:roll_id>")
    def api_edit_roll(roll_id):
        if db.get_roll(conn, roll_id) is None:
            return jsonify(error="roll not found"), 404
        data = _body()
        patch = {}
        if "camera_id" in data:
            if not isinstance(data["camera_id"], int) or isinstance(data["camera_id"], bool) \
                    or db.get_camera(conn, data["camera_id"]) is None:
                raise BadRequest("unknown camera_id")
            patch["camera_id"] = data["camera_id"]
        if "film_id" in data:
            if not isinstance(data["film_id"], int) or isinstance(data["film_id"], bool) \
                    or db.get_film(conn, data["film_id"]) is None:
                raise BadRequest("unknown film_id")
            patch["film_id"] = data["film_id"]
        if "shot_at" in data:
            patch["shot_at"] = _datetime(data, "shot_at")
        if "note" in data:
            patch["note"] = _note(data)
        if "roll_no" in data:
            rn = _str(data, "roll_no", required=True, max_len=20)
            if db.roll_no_taken(conn, rn, exclude_id=roll_id):
                raise BadRequest("that roll number is already in use")
            patch["roll_no"] = rn
        if not patch:
            raise BadRequest("no known fields in body")
        return jsonify(db.update_roll(conn, roll_id, patch))

    @app.delete("/api/rolls/<int:roll_id>")
    def api_delete_roll(roll_id):
        if not db.delete_roll(conn, roll_id):
            return jsonify(error="roll not found"), 404
        return jsonify(deleted=True)

    @app.put("/api/rolls/<int:roll_id>/locations/<int:location_id>")
    def api_edit_roll_location(roll_id, location_id):
        if db.get_roll(conn, roll_id) is None:
            return jsonify(error="roll not found"), 404
        data = _body()
        entry = None
        patch = {}
        if "note" in data:
            patch["note"] = _note(data)
        if "visited_at" in data:
            patch["visited_at"] = _datetime(data, "visited_at")
        if patch:
            entry = db.update_roll_location(conn, roll_id, location_id, patch)
            if entry is None:
                return jsonify(error="that roll has no entry for that location"), 404
        # change WHERE this roll entry was shot (relink to another place)
        target = None
        if "location_name" in data:
            name = _str(data, "location_name", required=True, max_len=120)
            target = db.get_or_create_location(conn, name)["id"]
        elif "location_id" in data:
            if not isinstance(data["location_id"], int) or isinstance(data["location_id"], bool) \
                    or db.get_location(conn, data["location_id"]) is None:
                raise BadRequest("unknown location_id")
            target = data["location_id"]
        if target is not None:
            entry = db.relink_roll_location(conn, roll_id, location_id, target)
            if entry is None:
                return jsonify(error="that roll has no entry for that location"), 404
        if entry is None:
            raise BadRequest("no known fields in body")
        return jsonify(entry)

    @app.put("/api/locations/<int:location_id>")
    def api_edit_location(location_id):
        if db.get_location(conn, location_id) is None:
            return jsonify(error="location not found"), 404
        data = _body()
        patch = {}
        if "name" in data:
            patch["name"] = _str(data, "name", required=True)
        if "note" in data:
            patch["note"] = _note(data)
        if "visited_at" in data:
            patch["visited_at"] = _datetime(data, "visited_at")
        if not patch:
            raise BadRequest("no known fields in body")
        return jsonify(db.update_location(conn, location_id, patch))

    @app.delete("/api/locations/<int:location_id>")
    def api_delete_location(location_id):
        if db.get_location(conn, location_id) is None:
            return jsonify(error="location not found"), 404
        if not db.delete_location(conn, location_id):
            return jsonify(error="rolls still use this location - delete "
                                "those entries first"), 400
        return jsonify(deleted=True)

    # ------------------------------------------------------------ settings

    @app.get("/api/settings")
    def api_get_settings():
        return jsonify(db.get_settings(conn))

    @app.put("/api/settings")
    def api_put_settings():
        data = _body()
        patch = {}
        if "theme" in data:
            if data["theme"] not in THEMES:
                raise BadRequest("theme must be auto|light|dark")
            patch["theme"] = data["theme"]
        if "show_times" in data:
            v = data["show_times"]
            if isinstance(v, bool):
                patch["show_times"] = "1" if v else "0"
            elif v in ("0", "1", 0, 1):
                patch["show_times"] = str(v)
            else:
                raise BadRequest("show_times must be a boolean")
        if not patch:
            raise BadRequest("no known settings in body")
        return jsonify(db.set_settings(conn, patch))

    return app

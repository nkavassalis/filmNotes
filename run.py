#!/usr/bin/env python3
"""filmNotes entry point:  python run.py [--config config.yaml] [--db PATH]"""
import argparse
import logging
import os

from filmnotes import db
from filmnotes.web import create_app

DEFAULTS = {"server": {"host": "127.0.0.1", "port": 8961, "data_dir": "data"}}


def load_config(path):
    import yaml
    cfg = {k: dict(v) for k, v in DEFAULTS.items()}
    if os.path.exists(path):
        with open(path) as f:
            loaded = yaml.safe_load(f) or {}
        for sect, vals in (loaded or {}).items():
            cfg.setdefault(sect, {})
            cfg[sect].update(vals or {})
    return cfg


def main():
    ap = argparse.ArgumentParser(description="filmNotes")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--db", default=None, help="override sqlite path (tests)")
    ap.add_argument("--host", default=None)
    ap.add_argument("--port", type=int, default=None)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    cfg = load_config(args.config)
    host = args.host or cfg["server"]["host"]
    port = args.port or int(cfg["server"]["port"])
    if args.db:
        db_path = args.db
    else:
        os.makedirs(cfg["server"]["data_dir"], exist_ok=True)
        db_path = os.path.join(cfg["server"]["data_dir"], "filmnotes.sqlite")

    app = create_app(db_path)
    print(f"filmNotes listening on http://{host}:{port}  (db: {db_path})")
    app.run(host=host, port=port, threaded=True, debug=False)


if __name__ == "__main__":
    main()

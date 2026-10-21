"""Static UI contract: the JS and the template must agree.

Guards against the classic rot: app.js reaches for an id that no longer
exists, overlays ship visible, or the [hidden] rule gets weakened by a
later `display:flex` (rssgate learned this the hard way).
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "filmnotes" / "templates" / "index.html").read_text()
SCRIPT = (ROOT / "filmnotes" / "static" / "app.js").read_text()
CSS = (ROOT / "filmnotes" / "static" / "style.css").read_text()


def test_hidden_rule_is_important():
    assert re.search(r"\[hidden\]\s*\{\s*display:\s*none\s*!important", CSS)


def test_overlays_ship_hidden():
    for mid in ("roll-modal", "loc-modal", "entry-modal", "settings-modal",
                "veil", "toast"):
        tag = re.search(rf'<(section|div) id="{mid}"[^>]*>', TEMPLATE)
        assert tag, f"#{mid} missing"
        assert "hidden" in tag.group(0), f"#{mid} must ship hidden"


def test_every_js_id_exists_in_template():
    used = set(re.findall(r'\$\("([\w-]+)"\)', SCRIPT))
    present = set(re.findall(r'id="([\w-]+)"', TEMPLATE))
    # ids created dynamically by render functions
    dynamic = {"new-camera", "add-camera", "new-film", "add-film"}
    missing = used - present - dynamic
    assert not missing, f"app.js references unknown ids: {sorted(missing)}"


def test_every_drawer_page_has_a_route():
    pages = set(re.findall(r'data-page="([\w-]+)"', TEMPLATE))
    assert pages == {"rolls", "locations", "cameras", "film"}
    for p in pages:
        assert f'"{p}"' in SCRIPT


def test_pwa_wiring():
    assert 'rel="manifest"' in TEMPLATE
    assert 'apple-touch-icon' in TEMPLATE
    assert 'apple-mobile-web-app-capable' in TEMPLATE
    assert 'viewport-fit=cover' in TEMPLATE
    manifest = (ROOT / "filmnotes" / "static" / "manifest.webmanifest").read_text()
    assert '"display": "standalone"' in manifest
    for icon in ("icon-192.png", "icon-512.png", "apple-touch-icon.png",
                 "favicon.svg"):
        assert (ROOT / "filmnotes" / "static" / icon).exists()


def test_bottombar_hidden_only_for_settings():
    assert "body.settings-open #bottombar" in CSS
    assert "settings-open" in SCRIPT
    # only three rules may hide anything: the [hidden] contract, the
    # settings-open bottombar, and .add-loc (must claim no space when
    # edit mode is off - user requirement)
    assert CSS.count("display: none") == 3
    assert ".add-loc" in CSS and "body.edit-mode .add-loc" in CSS

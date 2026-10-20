import pytest

from filmnotes import db
from filmnotes.web import create_app


@pytest.fixture()
def conn(tmp_path):
    c = db.connect(str(tmp_path / "test.sqlite"))
    db.init_db(c)
    yield c
    c.close()


@pytest.fixture()
def app(tmp_path):
    return create_app(str(tmp_path / "app.sqlite"))


@pytest.fixture()
def client(app):
    return app.test_client()

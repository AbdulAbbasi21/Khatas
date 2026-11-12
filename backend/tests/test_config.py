from app.core.config import db_url, site_url


def test_db_url_uses_psycopg3_driver():
    assert db_url("postgres://u:p@h:5432/d") == "postgresql+psycopg://u:p@h:5432/d"
    assert db_url("postgresql://u:p@h/d") == "postgresql+psycopg://u:p@h/d"
    assert db_url("postgresql+psycopg://u:p@h/d") == "postgresql+psycopg://u:p@h/d"
    assert db_url("sqlite:///./test.db") == "sqlite:///./test.db"


def test_site_url_adds_https_to_bare_host():
    assert site_url("khataz-web.onrender.com") == "https://khataz-web.onrender.com"
    assert site_url("http://localhost:5173/") == "http://localhost:5173"
    assert site_url("") == ""

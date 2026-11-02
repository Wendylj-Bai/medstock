from pathlib import Path

import pytest

import db
import streamlit as st
from streamlit.testing.v1 import AppTest

import auth

APP = Path(__file__).parent / "app.py"


@pytest.fixture(autouse=True)
def clean_caches():
    st.cache_resource.clear()
    st.cache_data.clear()
    yield
    st.cache_resource.clear()
    st.cache_data.clear()


def no_db(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("homepage must not touch the database")
    monkeypatch.setattr(db, "connect", boom)


@pytest.fixture
def home_to_demo(tmp_path, monkeypatch):
    orig = db.connect
    db_path = tmp_path / "app.db"
    opened = []

    def patched(*a, **k):
        c = orig(db_path)
        opened.append(c)
        return c

    monkeypatch.setattr(db, "connect", patched)
    at = AppTest.from_file(str(APP), default_timeout=180)
    at.secrets["auth"] = {"users": {"tester": auth.hash_password("s3cret")}}
    at.run()
    yield at
    st.cache_resource.clear()
    st.cache_data.clear()
    for c in opened:
        c.close()


def test_home_renders_without_database(monkeypatch):
    no_db(monkeypatch)
    at = AppTest.from_file(str(APP), default_timeout=180)
    at.run()
    assert not at.exception
    assert len(at.tabs) == 0


def test_home_has_brand_headline_sections_and_caption(monkeypatch):
    no_db(monkeypatch)
    at = AppTest.from_file(str(APP), default_timeout=180)
    at.run()
    html = "\n".join(h.value for h in at.html)
    for text in ("MedStock", "Supply chain portfolio project",
                 "Why hospital inventory is hard", "What it does", "How a simulated day works",
                 "What came from class and what I added", "Built with", "Scope and limits"):
        assert text in html
    caption = " | ".join(c.value for c in at.caption)
    assert "needs a sign-in" in caption


def test_home_has_no_tabs_or_stock_controls(monkeypatch):
    no_db(monkeypatch)
    at = AppTest.from_file(str(APP), default_timeout=180)
    at.run()
    assert len(at.tabs) == 0
    assert all(b.label != "Issue stock" for b in at.button)


def test_fresh_session_defaults_to_home(monkeypatch):
    no_db(monkeypatch)
    at = AppTest.from_file(str(APP), default_timeout=180)
    at.run()
    assert not at.exception
    assert at.button(key="open_demo").label == "Explore the inventory demo"


def sign_in(at, user="tester", pw="s3cret"):
    at.button(key="open_demo").click().run()
    at.text_input(key="login_user").input(user)
    at.text_input(key="login_pass").input(pw)
    at.button[[b.label for b in at.button].index("Sign in")].click().run()
    return at


def test_open_demo_enters_app_with_all_tabs(home_to_demo):
    at = sign_in(home_to_demo)
    assert not at.exception
    assert at.session_state["view"] == "demo"
    assert len(at.tabs) == 12


def test_back_home_keeps_session_state(home_to_demo):
    at = home_to_demo
    at.session_state["marker"] = "kept"
    sign_in(at)
    at.button(key="back_home").click().run()
    assert not at.exception
    assert at.button(key="open_demo").label == "Explore the inventory demo"
    assert len(at.tabs) == 0
    assert at.session_state["marker"] == "kept"


def test_repeat_navigation_home_demo_home_demo(home_to_demo):
    at = sign_in(home_to_demo)
    assert len(at.tabs) == 12
    at.button(key="back_home").click().run()
    assert len(at.tabs) == 0
    at.button(key="open_demo").click().run()
    assert not at.exception
    assert len(at.tabs) == 12


def test_demo_needs_sign_in(home_to_demo):
    at = home_to_demo
    at.button(key="open_demo").click().run()
    assert len(at.tabs) == 0 and at.session_state["view"] == "login"
    at.session_state["view"] = "demo"                     # skipping the login page does not work
    at.run()
    assert len(at.tabs) == 0 and at.session_state["view"] == "login"


def test_wrong_password_is_refused(home_to_demo):
    at = sign_in(home_to_demo, pw="nope")
    assert not at.exception and len(at.tabs) == 0
    assert any("incorrect" in e.value for e in at.error)
    assert "user" not in at.session_state


def test_sign_out_locks_the_demo_again(home_to_demo):
    at = sign_in(home_to_demo)
    at.button(key="sign_out").click().run()
    assert len(at.tabs) == 0 and "user" not in at.session_state
    at.button(key="open_demo").click().run()
    assert len(at.tabs) == 0 and at.session_state["view"] == "login"


def test_password_hashing():
    pw = "Qz-secret!"                                         # cannot occur inside a hex hash
    stored = auth.hash_password(pw)
    assert pw not in stored and auth.check_password(pw, stored)
    assert not auth.check_password("Qz-secret?", stored) and not auth.check_password(pw, "garbage")
    assert auth.hash_password(pw) != stored                   # salted: same password, different hash

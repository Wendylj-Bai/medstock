from pathlib import Path

import pytest

import db
import streamlit as st
from streamlit.testing.v1 import AppTest

import auth
import ui

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


def nav_count(at):
    """Number of sidebar menu buttons: one per page inside the demo, 0 on the homepage and sign-in page."""
    return sum(1 for b in at.button if (b.key or "").startswith("nav_"))


def test_home_renders_without_database(monkeypatch):
    no_db(monkeypatch)
    at = AppTest.from_file(str(APP), default_timeout=180)
    at.run()
    assert not at.exception
    assert nav_count(at) == 0


def test_home_has_brand_headline_sections_and_caption(monkeypatch):
    no_db(monkeypatch)
    at = AppTest.from_file(str(APP), default_timeout=180)
    at.run()
    html = "\n".join(h.value for h in at.html)
    for text in ("MedStock", "Supply chain portfolio project",
                 "Why hospital inventory is hard", "What it does", "A simulated day",
                 "What came from class and what I added", "Built with", "Scope and limits"):
        assert text in html
    assert "The demo is invite-only" in html


def test_home_has_no_tabs_or_stock_controls(monkeypatch):
    no_db(monkeypatch)
    at = AppTest.from_file(str(APP), default_timeout=180)
    at.run()
    assert nav_count(at) == 0
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
    assert nav_count(at) == len(ui.PAGES)


def test_back_home_keeps_session_state(home_to_demo):
    at = home_to_demo
    at.session_state["marker"] = "kept"
    sign_in(at)
    at.button(key="back_home").click().run()
    assert not at.exception
    assert at.button(key="open_demo").label == "Explore the inventory demo"
    assert nav_count(at) == 0
    assert at.session_state["marker"] == "kept"


def test_repeat_navigation_home_demo_home_demo(home_to_demo):
    at = sign_in(home_to_demo)
    assert nav_count(at) == len(ui.PAGES)
    at.button(key="back_home").click().run()
    assert nav_count(at) == 0
    at.button(key="open_demo").click().run()
    assert not at.exception
    assert nav_count(at) == len(ui.PAGES)


def test_demo_needs_sign_in(home_to_demo):
    at = home_to_demo
    at.button(key="open_demo").click().run()
    assert nav_count(at) == 0 and at.session_state["view"] == "login"
    at.session_state["view"] = "demo"                     # skipping the login page does not work
    at.run()
    assert nav_count(at) == 0 and at.session_state["view"] == "login"


def test_wrong_password_is_refused(home_to_demo):
    at = sign_in(home_to_demo, pw="nope")
    assert not at.exception and nav_count(at) == 0
    assert any("incorrect" in e.value for e in at.error)
    assert "user" not in at.session_state


def test_sign_out_locks_the_demo_again(home_to_demo):
    at = sign_in(home_to_demo)
    at.button(key="sign_out").click().run()
    assert nav_count(at) == 0 and "user" not in at.session_state
    at.button(key="open_demo").click().run()
    assert nav_count(at) == 0 and at.session_state["view"] == "login"


def test_password_hashing():
    pw = "Qz-secret!"                                         # cannot occur inside a hex hash
    stored = auth.hash_password(pw)
    assert pw not in stored and auth.check_password(pw, stored)
    assert not auth.check_password("Qz-secret?", stored) and not auth.check_password(pw, "garbage")
    assert auth.hash_password(pw) != stored                   # salted: same password, different hash


# ---------------------------------------------------------------------------
# Ask MedStock on the homepage
# ---------------------------------------------------------------------------
def homepage_html(at):
    return " ".join(e.proto.body for e in at.get("html"))


def test_homepage_stat_shows_read_only_ai_lookups(monkeypatch):
    import assistant
    import homepage
    assert homepage.AI_LOOKUPS == len(assistant.TOOLS) == 7       # the stat matches the real tool list
    assert not hasattr(homepage, "_test_count")
    no_db(monkeypatch)
    at = AppTest.from_file(str(APP), default_timeout=180)
    at.run()
    html = homepage_html(at)
    assert "<b>7</b>" in html and "Read-only AI lookups" in html
    assert "Automated tests" not in html


def test_homepage_introduces_ask_medstock_honestly(monkeypatch):
    no_db(monkeypatch)
    at = AppTest.from_file(str(APP), default_timeout=180)
    at.run()
    html = homepage_html(at)
    assert 'id="ask"' in html and "Ask a question, get an answer from the data" in html
    assert "read-only" in html.lower() and "Gemini" in html and "fictional" in html
    for q in ["Which Vital items are most at risk of running out?", "Are any vendors disrupted or late right now?"]:
        assert q in html
    assert "autonomous" not in html.lower()                       # never described as autonomous
    assert "Coming later" in html                                   # approval-based actions are future work
    assert at.button(key="open_ask").label == "Sign in to try Ask MedStock"


def test_ask_cta_signed_out_goes_through_sign_in_to_ask_medstock(home_to_demo):
    at = home_to_demo
    at.button(key="open_ask").click().run()
    assert at.session_state["view"] == "login" and at.session_state["page"] == "Ask MedStock"
    assert nav_count(at) == 0                                       # still locked
    at.text_input(key="login_user").input("tester")
    at.text_input(key="login_pass").input("s3cret")
    at.button[[b.label for b in at.button].index("Sign in")].click().run()
    assert not at.exception
    assert at.session_state["view"] == "demo" and at.session_state["page"] == "Ask MedStock"


def test_ask_cta_signed_in_opens_ask_medstock_directly(home_to_demo):
    at = sign_in(home_to_demo)
    at.button(key="back_home").click().run()
    assert at.button(key="open_ask").label == "Open Ask MedStock"
    at.button(key="open_ask").click().run()
    assert not at.exception
    assert at.session_state["view"] == "demo" and at.session_state["page"] == "Ask MedStock"
    assert nav_count(at) == len(ui.PAGES)

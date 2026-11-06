import json
import re
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
    assert "read-only" in html.lower() and "governed" in html.lower() and "fictional" in html
    assert "Gemini" not in html                              # provider details belong in Help, privacy and docs
    for q in ["Which Vital items are most at risk of running out?", "Are any vendors disrupted or late right now?"]:
        assert q in html
    assert "autonomous" not in html.lower()                       # never described as autonomous
    assert "Coming later" in html                                   # approval-based actions are future work
    assert at.button(key="open_ask").label == "Sign in to try Ask MedStock"


def test_homepage_presents_agentic_ai_as_built_and_planned(monkeypatch):
    no_db(monkeypatch)
    at = AppTest.from_file(str(APP), default_timeout=180)
    at.run()
    html = homepage_html(at)
    assert 'id="agentic"' in html
    assert "Agentic AI for governed supply-chain decisions" in html
    assert "people retain approval" in html and "governed tools" in html
    assert "Gemini" not in html                              # provider stays in Ask MedStock, Help, privacy and docs

    # the agent table: Ask MedStock is built, the three team agents are coming later
    table = html[html.index('class="ms-agent-table"'):html.index("</table>")]
    rows = re.findall(r'<tr><td data-label="Agent">([^<]+)</td><td data-label="Status">'
                      r'<span class="ms-agent-status (\w+)">([^<]+)</span>', table)
    assert rows == [("Ask MedStock", "built", "Built"),
                    ("Inventory Impact Agent", "planned", "Coming later"),
                    ("Sourcing Agent", "planned", "Coming later"),
                    ("Recovery Planner Agent", "planned", "Coming later")]
    for old in ("Buyer Agent", "Disruption Agent"):              # superseded by the recovery team
        assert old not in html
    assert "Policy Analyst" not in table                          # longer-term roadmap only
    for label in ("Agent", "Status", "Problem it helps solve", "How it works"):
        assert f'data-label="{label}"' in table                   # phones stack each cell under its label

    assert "The engine calculates" in html and "Agents investigate and coordinate" in html
    assert "People keep authority" in html
    assert "investigate the same event in" in html and "parallel" in html
    assert "How MedStock's agent team works" in html
    assert "The Case Coordinator is not another AI agent" in html
    assert "Coordinated Supply Recovery Team" in html
    assert "No agent can directly" in html
    assert "autonomous" not in html.lower()
    assert "agentic-workflow.html?theme=light" in html


def test_both_diagrams_load_from_the_apps_own_address(monkeypatch):
    # On Streamlit Cloud the app lives under /~/+/, so the frames must use a relative path
    # ("app/static/...") that resolves inside it. A root path ("/app/static/...") leaves the app and gets a
    # 303 redirect, so the diagram never loads. st.iframe would also show a relative path as text, which is
    # why the frames use components.iframe.
    import homepage
    no_db(monkeypatch)
    at = AppTest.from_file(str(APP), default_timeout=180)
    at.run()
    frames = at.get("iframe")
    assert [e.proto.src for e in frames] == ["app/static/home/agentic-workflow.html?theme=light&embed=1",
                                             "app/static/home/workflow.html?theme=light&embed=1"]
    assert all(not e.proto.src.startswith("/") and not e.proto.srcdoc for e in frames)
    assert homepage.IMG == "app/static/home/"
    root = Path(__file__).parent / "static/home"
    assert (root / "agentic-workflow.html").is_file() and (root / "workflow.html").is_file()


def test_agent_diagram_frame_shrinks_with_its_wrapper_below_desktop():
    # Streamlit fixes the iframe's wrapper at height 700px and flex-basis 700px. Shrinking only the iframe
    # left up to 570px of blank space on tablets and phones, so both must be released below desktop.
    import homepage
    css = re.sub(r"\s+", " ", homepage.CSS)
    block = re.search(r"@media \(max-width:1100px\)\{ (\.st-key-agentic_frame .*?)\} \}", css)
    assert block, "responsive rules for the agent diagram are missing"
    rules = block.group(1)
    wrapper = re.search(r'\.st-key-agentic_frame \[data-testid="stElementContainer"\]\{([^}]*)', rules).group(1)
    assert "height:auto !important" in wrapper and "flex:0 0 auto !important" in wrapper
    frame = re.search(r"\.st-key-agentic_frame iframe\{([^}]*)", rules).group(1)
    assert "height:auto !important" in frame and "aspect-ratio:16/9" in frame and "max-height:700px" in frame
    # desktop keeps the 700px frame: no sizing override outside the media query
    outside = css.replace(block.group(0), "")
    assert "aspect-ratio" not in outside and "flex:0 0 auto" not in outside


def test_agentic_workflow_matches_the_team_design():
    root = Path(__file__).parent
    spec = json.loads((root / "docs/agentic_workflow.json").read_text())
    assert spec["meta"]["quality_profile"] == "showcase"
    assert [v["label"] for v in spec["meta"]["views"]] == ["Built today", "Agent team", "Governance"]
    labels = {n["id"]: n["label"] for n in spec["nodes"]}
    for name in ("Ask MedStock", "Inventory Impact Agent", "Sourcing Agent", "Recovery Planner Agent",
                 "Case Coordinator", "Human decision", "Audit log"):
        assert name in labels.values()
    edges = {(e["from"], e["to"]) for e in spec["edges"]}
    # both specialists start from the coordinator and report to the planner (parallel, structured handoffs)
    for agent in ("impact_agent", "sourcing_agent"):
        assert ("case_coordinator", agent) in edges and (agent, "recovery_planner") in edges
    # the proposal is validated, then approved, before existing functions change anything
    assert ("recovery_planner", "validation") in edges and ("validation", "human_approval") in edges
    assert ("human_approval", "existing_functions") in edges
    assert not any(e[1] == "existing_functions" and e[0] != "human_approval" for e in edges)
    coord = next(n for n in spec["nodes"] if n["id"] == "case_coordinator")
    assert coord["tag"] == "NOT AN AI AGENT"
    page = (root / "static/home/agentic-workflow.html").read_text(encoding="utf-8")
    assert "Recovery Planner Agent" in page and "Buyer Agent" not in page
    assert "Gemini" not in json.dumps(spec) and "Gemini" not in page


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

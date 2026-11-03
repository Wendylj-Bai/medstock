"""
auth.py: Simple sign-in for the demo.

The homepage is public. The demo (all tabs) needs a username and password.

Accounts live in .streamlit/secrets.toml (never in the code or the docs), with the
password stored only as a salted PBKDF2 hash:

    [auth.users]
    some_name = "pbkdf2_sha256$200000$<salt>$<hash>"

To add or change an account, run in the project folder:

    .venv/bin/python auth.py add <username>

It asks for the password (hidden) and prints the line to paste into secrets.toml.
On Streamlit Community Cloud, paste the same lines into the app's Secrets settings.
"""

import getpass
import hashlib
import hmac
import secrets
import sys
import time
from pathlib import Path

import streamlit as st

ITERATIONS = 200_000
MAX_FREE_ATTEMPTS = 5          # after this many wrong passwords, each new try is slowed down


def hash_password(password, salt=None, iterations=ITERATIONS):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), iterations).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def check_password(password, stored):
    try:
        scheme, iterations, salt, _ = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        return hmac.compare_digest(hash_password(password, salt, int(iterations)), stored)
    except (ValueError, AttributeError):
        return False


def configured_users():
    """{username: stored hash} from Streamlit secrets; empty if nothing is configured."""
    try:
        return dict(st.secrets.get("auth", {}).get("users", {}))
    except Exception:            # no secrets file at all
        return {}


def verify(username, password, users=None):
    users = configured_users() if users is None else users
    stored = users.get(username.strip())
    if stored is None:
        hash_password(password)  # same work as a real check, so timing does not reveal valid names
        return False
    return check_password(password, stored)


def current_user():
    return st.session_state.get("user")


def sign_out():
    st.session_state.pop("user", None)
    st.session_state["view"] = "home"


def render_login():
    """Sign-in page shown between the homepage and the demo."""
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        st.image(str(Path(__file__).parent / "assets" / "logo_wordmark.svg"), width=220)
        st.caption("Sign in to open the inventory demo. Access is by invitation.")
        if not configured_users():
            st.warning("Sign-in is not set up on this server yet (no accounts in the app's secrets).")
        with st.form("login_form"):
            username = st.text_input("Username", key="login_user")
            password = st.text_input("Password", type="password", key="login_pass")
            submitted = st.form_submit_button("Sign in", type="primary", width="stretch")
        if submitted:
            fails = st.session_state.get("login_fails", 0)
            if fails >= MAX_FREE_ATTEMPTS:
                time.sleep(min(2 ** (fails - MAX_FREE_ATTEMPTS), 30))
            if verify(username, password):
                st.session_state.update(user=username.strip(), view="demo", login_fails=0)
                st.rerun()
            st.session_state["login_fails"] = fails + 1
            st.error("Username or password is incorrect.")
        if st.button("← Back to project home", key="login_back"):
            st.session_state["view"] = "home"
            st.rerun()


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "add":
        pw = getpass.getpass(f"Password for {sys.argv[2]}: ")
        if pw != getpass.getpass("Repeat it: "):
            sys.exit("Passwords do not match.")
        print("\nAdd this line under [auth.users] in .streamlit/secrets.toml:\n")
        print(f'{sys.argv[2]} = "{hash_password(pw)}"')
    else:
        print("Usage: python auth.py add <username>")

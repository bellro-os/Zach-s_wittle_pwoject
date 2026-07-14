"""SWVA MLS endpoint discovery — try common Paragon subdomain patterns.

The user provided credentials (username 845594077, password Cummings) without
a confirmed RETS login URL. This script probes a fast list of plausible
Paragon-hosted Virginia regional MLS endpoints, attempting a login on each.
First success wins; otherwise, all candidates fail and we bail with a clear
error so the user knows to look up the URL from their member portal.

Run:
    PYTHONPATH=src python scripts/discover_swva_endpoint.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from rets import Session


CREDS_USER = "845594077"
CREDS_PASS = "Cummings"

CANDIDATES = [
    # Paragon subdomain conventions
    ("https://swva-rets.paragonrels.com/rets/fnisrets.aspx/SWVA/login?rets-version=rets/1.8", "SWVA"),
    ("https://swvar-rets.paragonrels.com/rets/fnisrets.aspx/SWVAR/login?rets-version=rets/1.8", "SWVAR"),
    ("https://swvarmls-rets.paragonrels.com/rets/fnisrets.aspx/SWVAR/login?rets-version=rets/1.8", "SWVARMLS"),
    ("https://southwestvamls-rets.paragonrels.com/rets/fnisrets.aspx/SWVA/login?rets-version=rets/1.8", "SOUTHWESTVAMLS"),
    ("https://svar-rets.paragonrels.com/rets/fnisrets.aspx/SVAR/login?rets-version=rets/1.8", "SVAR"),
    ("https://rvar-rets.paragonrels.com/rets/fnisrets.aspx/RVAR/login?rets-version=rets/1.8", "RVAR"),
    ("https://roanoke-rets.paragonrels.com/rets/fnisrets.aspx/RVAR/login?rets-version=rets/1.8", "ROANOKE"),
    # Less likely but quick to try
    ("https://va-rets.paragonrels.com/rets/fnisrets.aspx/VA/login?rets-version=rets/1.8", "VA"),
]


def try_login(login_url: str, user: str, pw: str, timeout_s: int = 15) -> tuple[bool, str]:
    try:
        sess = Session(
            login_url=login_url, username=user, password=pw,
            user_agent="mls-bot/0.1",
        )
        sess.login()
        # If login succeeded, try a metadata call to confirm read access
        resources = sess.get_resource_metadata()
        try:
            sess.logout()
        except Exception:
            pass
        return True, f"login OK; {len(resources)} resources visible"
    except Exception as e:
        return False, str(e)[:120]


def main() -> int:
    load_dotenv()
    print(f"probing {len(CANDIDATES)} candidate Paragon endpoints with user={CREDS_USER}...")
    print()
    results: list[tuple[str, str, bool, str, float]] = []
    success = None
    for url, label in CANDIDATES:
        t0 = time.time()
        ok, msg = try_login(url, CREDS_USER, CREDS_PASS)
        elapsed = time.time() - t0
        results.append((label, url, ok, msg, elapsed))
        flag = "OK " if ok else "X  "
        print(f"  [{flag}] {label:18s} ({elapsed:>4.1f}s)  {msg[:90]}")
        if ok:
            success = (label, url)
            break

    print()
    if success:
        label, url = success
        print(f"=== SUCCESS: {label} at {url} ===")
        print(f"   add to .env:")
        print(f"     MLS2_RETS_LOGIN_URL={url}")
        print(f"     MLS2_RETS_USERNAME={CREDS_USER}")
        print(f"     MLS2_RETS_PASSWORD={CREDS_PASS}")
        print(f"     MLS2_RETS_USER_AGENT=mls-bot/0.1")
        return 0

    print(f"=== ALL CANDIDATES FAILED ===")
    print()
    print("Next steps:")
    print("  1. Check your SWVA member portal (login.svaaor.org or the realtor")
    print("     dashboard you use) for a 'Data Feed' / 'RETS Configuration' link.")
    print("  2. The exact login URL will look like:")
    print("       https://<subdomain>.paragonrels.com/rets/fnisrets.aspx/<MLS>/login?rets-version=rets/1.8")
    print("  3. Some MLSes also require a User-Agent password (separate from")
    print("     username/password). If yours does, you'll see UA Auth in the")
    print("     portal.")
    print("  4. Once you have the correct URL, set MLS2_RETS_LOGIN_URL in .env")
    print("     and re-run scripts/rets_pull_all.py with that as the source.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

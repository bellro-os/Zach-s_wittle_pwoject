"""One-shot RETS metadata dump.

Logs in, lists resources + classes, and dumps the field metadata for the
Property resource (system name, standard name, long name, type, lookup) so we
can pin the field map for the ingest path before pulling any listings.

Read-only. Does not run a SEARCH. Writes everything to
    outputs/rets_metadata/

Run:
    PYTHONPATH=src python scripts/rets_explore.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from rets import Session


OUT_DIR = Path("outputs/rets_metadata")


def _dump_json(name: str, obj: object) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    p = OUT_DIR / name
    with p.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, default=str)
    print(f"  wrote {p}")


def main() -> int:
    load_dotenv()
    login = os.environ["MLS_RETS_LOGIN_URL"]
    user = os.environ["MLS_RETS_USERNAME"]
    pw = os.environ["MLS_RETS_PASSWORD"]
    ua = os.environ.get("MLS_RETS_USER_AGENT") or "mls-bot/0.1"
    ua_pw = os.environ.get("MLS_RETS_UA_PASSWORD") or None

    print(f"login: {login}")
    print(f"user:  {user}")
    print(f"UA:    {ua}{'  (with UA password)' if ua_pw else ''}")

    sess = Session(
        login_url=login,
        username=user,
        password=pw,
        user_agent=ua,
        user_agent_password=ua_pw,
    )
    sess.login()
    print("[OK] logged in")

    resources = sess.get_resource_metadata()
    print(f"\nresources: {len(resources)}")
    for r in resources:
        rid = getattr(r, "resource_id", None) or getattr(r, "ResourceID", None) or r
        print(f"  - {rid}")
    _dump_json("resources.json", [r.__dict__ if hasattr(r, "__dict__") else r for r in resources])

    print("\nclasses for Property:")
    classes = sess.get_class_metadata("Property")
    for c in classes:
        cid = getattr(c, "class_name", None) or getattr(c, "ClassName", None) or c
        print(f"  - {cid}")
    _dump_json("property_classes.json", [c.__dict__ if hasattr(c, "__dict__") else c for c in classes])

    for c in classes:
        cid = getattr(c, "class_name", None) or getattr(c, "ClassName", None)
        if not cid:
            continue
        try:
            tbl = sess.get_table_metadata("Property", cid)
        except Exception as e:
            print(f"  [skip {cid}: {e}]")
            continue
        print(f"  fields in Property/{cid}: {len(tbl)}")
        _dump_json(f"property_{cid}_fields.json",
                   [t.__dict__ if hasattr(t, "__dict__") else t for t in tbl])

    sess.logout()
    print("\n[OK] logout")
    return 0


if __name__ == "__main__":
    sys.exit(main())

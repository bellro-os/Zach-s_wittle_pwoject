"""RETS Agent + Office directory pull.

Resolves the numeric IDs in our listings (list_agent, list_office) to actual
names + contact info. Writes to:
    data/mls/agents.jsonl   — one row per agent
    data/mls/offices.jsonl  — one row per office
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from .rets_pull import open_session


_AGENT_FIELDS = (
    "U_AgentID", "U_UserFirstName", "U_UserLastName", "U_LoginName",
    "U_HiddenOrgID",  # office ID
    "U_Email", "U_PhoneNumber1", "U_PhoneNumber2", "U_PhoneNumber3",
    "U_Status", "U_AddressStreet", "U_MailAddressStreet",
)

_OFFICE_FIELDS = (
    "O_OfficeID", "O_OrganizationName", "O_NameLegal",
    "O_PhoneAreaCode", "O_PhoneNumber",
    "O_FullStreetAddress", "O_City", "O_State", "O_PostalCode",
)


def _slim(raw: dict, keep: tuple[str, ...]) -> dict:
    return {k: raw.get(k) for k in keep if raw.get(k) not in (None, "")}


def pull_directory(
    out_agents: Path | str = "data/mls/agents.jsonl",
    out_offices: Path | str = "data/mls/offices.jsonl",
) -> dict:
    out_agents = Path(out_agents)
    out_offices = Path(out_offices)
    out_agents.parent.mkdir(parents=True, exist_ok=True)

    sess = open_session()
    started = time.time()
    try:
        # Agents
        n_agents = 0
        with out_agents.open("w", encoding="utf-8") as f:
            results = sess.search(resource="Agent", resource_class="Agent",
                                   dmql_query="(U_AgentID=0+)",
                                   limit=9_999_999, standard_names=0, auto_offset=True)
            for raw in results:
                f.write(json.dumps(_slim(raw, _AGENT_FIELDS), default=str) + "\n")
                n_agents += 1
        # Offices
        n_offices = 0
        with out_offices.open("w", encoding="utf-8") as f:
            results = sess.search(resource="Office", resource_class="Office",
                                   dmql_query="(O_OfficeID=0+)",
                                   limit=9_999_999, standard_names=0, auto_offset=True)
            for raw in results:
                f.write(json.dumps(_slim(raw, _OFFICE_FIELDS), default=str) + "\n")
                n_offices += 1
    finally:
        try:
            sess.logout()
        except Exception:
            pass

    return {
        "agents": n_agents,
        "offices": n_offices,
        "elapsed_s": round(time.time() - started, 1),
    }

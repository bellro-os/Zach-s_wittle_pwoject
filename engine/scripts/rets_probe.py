"""Probe NRV MLS Paragon RETS server and dump metadata for field mapping.

Run once with your creds in .env:

    python scripts/rets_probe.py

Outputs to data/metadata/:
    capabilities.json        -- URLs returned by Login
    resources.xml            -- all RETS resources (expect at least Property)
    classes_Property.xml     -- classes under Property (residential, land, etc.)
    tables_Property_<cls>.xml -- field definitions for each class
    lookups_Property.xml     -- lookup table index
    search_sample_<cls>.xml  -- 1-row search to verify read access
    summary.json             -- parsed summary for the next code-gen step

No database required. Safe to run repeatedly.
"""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from mls_bot.config import load  # noqa: E402

OUT = ROOT / "data" / "metadata"
OUT.mkdir(parents=True, exist_ok=True)

RETS_VERSION = "RETS/1.7.2"


def _capabilities(body: str, login_url: str) -> dict[str, str]:
    """Parse the key=value capability block Paragon returns in Login body."""
    caps: dict[str, str] = {}
    for line in body.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip()
        if not k or k.startswith("<"):
            continue
        caps[k] = v
    base = urlparse(login_url)
    root = f"{base.scheme}://{base.netloc}"
    absolutes = {}
    for k in ("Login", "Logout", "GetMetadata", "Search", "GetObject", "Action"):
        if k in caps:
            url = caps[k]
            absolutes[k] = url if url.startswith("http") else urljoin(root, url)
    return {**caps, **absolutes}


def _extract_rets_body(xml_text: str) -> str:
    """Paragon wraps Login responses in <RETS><RETS-RESPONSE>body</RETS-RESPONSE></RETS>."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return xml_text
    resp = root.find(".//RETS-RESPONSE")
    if resp is None:
        return xml_text
    text = resp.text
    if not text:
        return xml_text
    return text.strip()


def _check_reply(xml_text: str, what: str) -> None:
    """Raise if the RETS envelope signals an error code."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return
    code = root.attrib.get("ReplyCode", "0")
    if code != "0":
        msg = root.attrib.get("ReplyText", "")
        raise RuntimeError(f"{what} failed: ReplyCode={code} ReplyText={msg!r}")


def _parse_compact(xml_text: str) -> list[dict[str, str]]:
    """Parse a RETS COMPACT metadata block into a list of dicts.

    The payload shape is typically:
        <RETS ReplyCode='0' ReplyText='...'>
          <METADATA-TABLE Resource='Property' Class='RE_1' Version='...'>
            <COLUMNS>\tName\tType\tShort\t...\t</COLUMNS>
            <DATA>\tListPrice\tDecimal\tList $\t...\t</DATA>
            <DATA>...</DATA>
          </METADATA-TABLE>
        </RETS>
    """
    _check_reply(xml_text, "GetMetadata")
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    out: list[dict[str, str]] = []
    for block in root.iter():
        if not block.tag.startswith("METADATA-"):
            continue
        cols_el = block.find("COLUMNS")
        if cols_el is None:
            continue
        cols_text = (cols_el.text or "").strip("\t")
        if not cols_text:
            continue
        cols: list[str] = cols_text.split("\t")
        for data_el in block.findall("DATA"):
            data_text = (data_el.text or "").strip("\t")
            if not data_text:
                continue
            vals: list[str] = data_text.split("\t")
            row: dict[str, str] = dict(zip(cols, vals))
            # include block-level attrs so caller can see Resource / Class
            for ak, av in block.attrib.items():
                if av:
                    row.setdefault(f"_{ak}", av)
            out.append(row)
    return out


def main() -> int:
    s = load()
    if not s.rets_login_url or not s.rets_username or not s.rets_password:
        print("ERROR: set MLS_RETS_LOGIN_URL, MLS_RETS_USERNAME, MLS_RETS_PASSWORD in .env", file=sys.stderr)
        return 2

    auth = httpx.DigestAuth(s.rets_username, s.rets_password)
    headers = {
        "User-Agent": s.rets_user_agent or "mls-bot/0.1",
        "RETS-Version": RETS_VERSION,
        "Accept": "*/*",
    }

    with httpx.Client(auth=auth, headers=headers, timeout=60, follow_redirects=True) as c:
        print(f"-> Login  {s.rets_login_url}")
        r = c.get(s.rets_login_url)
        r.raise_for_status()
        body = _extract_rets_body(r.text)
        caps = _capabilities(body, s.rets_login_url)
        (OUT / "login_raw.xml").write_text(r.text, encoding="utf-8")
        (OUT / "capabilities.json").write_text(json.dumps(caps, indent=2), encoding="utf-8")
        print(f"   capabilities: {[k for k in caps if k[0].isupper()]}")

        get_meta = caps.get("GetMetadata")
        search = caps.get("Search")
        logout = caps.get("Logout")
        if not get_meta or not search:
            print("ERROR: Login body did not include GetMetadata/Search URLs", file=sys.stderr)
            print(body[:500])
            return 3

        def meta(kind: str, rid: str, fname: str) -> str:
            print(f"-> GetMetadata Type={kind} ID={rid}")
            rr = c.get(get_meta, params={"Type": kind, "ID": rid, "Format": "COMPACT"})
            rr.raise_for_status()
            (OUT / fname).write_text(rr.text, encoding="utf-8")
            return rr.text

        resources_xml = meta("METADATA-RESOURCE", "0", "resources.xml")
        resources = _parse_compact(resources_xml)

        summary: dict = {"capabilities": {k: v for k, v in caps.items() if k[0].isupper()},
                         "resources": resources, "classes": {}, "tables": {}, "lookups": {}}

        # Find Property resource
        prop_resource = next(
            (r["ResourceID"] for r in resources if r.get("ResourceID", "").lower() == "property"),
            None,
        ) or next(
            (r["ResourceID"] for r in resources if "propert" in r.get("StandardName", "").lower()),
            None,
        )
        if not prop_resource:
            print("ERROR: no Property resource found.", file=sys.stderr)
            print("Resources:", [r.get("ResourceID") for r in resources])
            return 4
        print(f"   Property resource = {prop_resource}")

        classes_xml = meta("METADATA-CLASS", prop_resource, f"classes_{prop_resource}.xml")
        classes = _parse_compact(classes_xml)
        summary["classes"][prop_resource] = classes
        print(f"   classes: {[c.get('ClassName') for c in classes]}")

        for cls in classes:
            cname = cls.get("ClassName")
            if not cname:
                continue
            tbl_xml = meta(
                "METADATA-TABLE",
                f"{prop_resource}:{cname}",
                f"tables_{prop_resource}_{cname}.xml",
            )
            tbl = _parse_compact(tbl_xml)
            summary["tables"][f"{prop_resource}:{cname}"] = tbl
            print(f"   {cname}: {len(tbl)} fields")

        lookups_xml = meta("METADATA-LOOKUP", prop_resource, f"lookups_{prop_resource}.xml")
        summary["lookups"][prop_resource] = _parse_compact(lookups_xml)

        # Smoke test: pull 1 row from the first class to confirm read works.
        if classes:
            first_cls = classes[0].get("ClassName")
            print(f"-> Search Resource={prop_resource} Class={first_cls} Limit=1")
            sr = c.get(search, params={
                "SearchType": prop_resource,
                "Class": first_cls,
                "Query": "(Status=|A,P,E,X,W,S)",  # likely over-broad but harmless with Limit=1
                "QueryType": "DMQL2",
                "Format": "COMPACT-DECODED",
                "Count": "1",
                "Limit": "1",
                "StandardNames": "0",
            })
            (OUT / f"search_sample_{first_cls}.xml").write_text(sr.text, encoding="utf-8")
            if sr.status_code == 200:
                print(f"   search sample saved ({len(sr.text)} bytes)")
            else:
                print(f"   search returned HTTP {sr.status_code} -- check search_sample_{first_cls}.xml")

        (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

        if logout:
            print(f"-> Logout")
            try:
                c.get(logout)
            except Exception:
                pass

    print(f"\nDone. Artifacts in {OUT}")
    print("Next step: share summary.json (or the tables_*.xml files) and I'll map the real field names into ingest/mls.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

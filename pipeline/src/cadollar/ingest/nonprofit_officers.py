"""Nonprofit leadership pay: named officers from IRS Form 990 Part VII.

Parses the e-file XMLs captured into sources/captured/990/ (one per
organization, fetched from the IRS's official bulk zips — see the YAML for
re-capture). Publishes, per organization: the filing year and its named
officers/directors/key employees with reported compensation, keyed by EIN and
name-indexed so the vendor drill can join without re-normalizing.

Fail-honest: an org with no captured XML simply isn't published (absence stays
absent); every org carries its filing year because the IRS releases returns on
a one-to-two-year lag.
"""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from typing import Any

from ..config import Settings
from ..publish.envelope import envelope
from ..sources import SourceConfig
from ..storage import Storage, read_manifest, write_manifest
from .csv_download import QualityGateError
from .entities import _read

_NS = "{http://www.irs.gov/efile}"


def _t(el: ET.Element, tag: str) -> str | None:
    return el.findtext(f"{_NS}{tag}")


def _num(el: ET.Element, tag: str) -> int:
    try:
        return int(float(_t(el, tag) or 0))
    except ValueError:
        return 0


def _parse_990(raw: bytes) -> dict[str, Any] | None:
    """Extract Part VII Section A (990) or the officer group (990-EZ)."""
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return None
    tax_year = root.findtext(f".//{_NS}TaxYr")
    people: list[dict[str, Any]] = []
    for grp in root.iter(f"{_NS}Form990PartVIISectionAGrp"):
        comp = _num(grp, "ReportableCompFromOrgAmt")
        related = _num(grp, "ReportableCompFromRltdOrgAmt")
        other = _num(grp, "OtherCompensationAmt")
        name = (_t(grp, "PersonNm") or "").strip()
        if not name:
            continue
        people.append(
            {
                "name": name,
                "title": (_t(grp, "TitleTxt") or "").strip(),
                "org_comp_usd": comp,
                "related_comp_usd": related,
                "other_comp_usd": other,
                "total_comp_usd": comp + related + other,
            }
        )
    if not people:  # 990-EZ officer list
        for grp in root.iter(f"{_NS}OfficerDirectorTrusteeEmplGrp"):
            name = (_t(grp, "PersonNm") or "").strip()
            if not name:
                continue
            comp = _num(grp, "CompensationAmt")
            people.append(
                {
                    "name": name,
                    "title": (_t(grp, "TitleTxt") or "").strip(),
                    "org_comp_usd": comp,
                    "related_comp_usd": 0,
                    "other_comp_usd": 0,
                    "total_comp_usd": comp,
                }
            )
    if not people:
        return None
    people.sort(key=lambda p: -p["total_comp_usd"])
    # the dossier shows leadership: everyone paid, plus unpaid board capped
    paid = [p for p in people if p["total_comp_usd"] > 0]
    return {
        "tax_year": int(tax_year) if tax_year else None,
        "people_reported": len(people),
        "paid_count": len(paid),
        "officers": (paid or people)[:15],
    }


def run_nonprofit_officers(storage: Storage, cfg: SourceConfig, settings: Settings) -> str:
    now = datetime.now(UTC)
    as_of = now.strftime("%Y-%m-%dT%H%M%SZ")
    manifest = read_manifest(storage, cfg.source)
    xml_dir = settings.sources_dir / "captured" / "990"
    files = sorted(xml_dir.glob("*_public.xml")) if xml_dir.exists() else []
    if not files:
        raise QualityGateError(f"{cfg.source}: no captured 990 XMLs in {xml_dir}")

    content_hash = hashlib.sha256(
        "".join(f"{f.name}:{f.stat().st_size}" for f in files).encode()
    ).hexdigest()
    if manifest.get("content_hash") == content_hash:
        manifest["checked_at"] = now.isoformat()
        write_manifest(storage, cfg.source, manifest)
        print(f"{cfg.source}: snapshot unchanged, no-op")
        return manifest["published_key"]

    # EIN -> registry org name (the join key the rest of the site uses)
    np = _read(storage, "published/nonprofits.json")
    ein_to_name: dict[str, str] = {}
    if np:
        for name, o in np["data"]["organizations"].items():
            ein = re.sub(r"\D", "", o.get("fein") or "")
            if len(ein) == 9:
                ein_to_name[ein] = name

    orgs: dict[str, dict[str, Any]] = {}
    name_index: dict[str, str] = {}
    total_officers = 0
    skipped = 0
    for f in files:
        ein = f.name.split("_", 1)[0]
        parsed = _parse_990(f.read_bytes())
        if parsed is None:
            skipped += 1
            continue
        reg_name = ein_to_name.get(ein)
        orgs[ein] = {"registry_name": reg_name, **parsed}
        total_officers += len(parsed["officers"])
        if reg_name:
            name_index[reg_name.upper()] = ein

    doc = {
        "org_count": len(orgs),
        "officer_count": total_officers,
        "xml_without_part_vii": skipped,
        "name_index": name_index,
        "organizations": orgs,
    }
    if total_officers < cfg.min_rows:
        raise QualityGateError(f"{cfg.source}: only {total_officers} officers parsed")

    key = "published/nonprofit_officers.json"
    storage.put_bytes(
        key,
        json.dumps(
            envelope(cfg, as_of=as_of, ingested_at=now.isoformat(), data=doc), indent=2
        ).encode(),
        "application/json",
    )
    write_manifest(
        storage,
        cfg.source,
        {
            "content_hash": content_hash,
            "row_count": total_officers,
            "as_of": as_of,
            "ingested_at": now.isoformat(),
            "checked_at": now.isoformat(),
            "published_key": key,
        },
    )
    print(
        f"{cfg.source}: {total_officers} named officers across {len(orgs)} organizations "
        f"-> {key}"
    )
    return key

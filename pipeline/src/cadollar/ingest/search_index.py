"""Search index: type an organization's name, jump straight to its money trail.

Derived, network-free — runs after every lane it consumes. For each named
state-checkbook vendor we resolve the drill path that reaches its profile
(area -> agency -> department -> checkbook -> vendor) and publish it, so the
site's search box can seed the same drill a click would, landing the visitor on
the vendor's profile with its cross-source dossier already in view.

Only vendors whose path is genuinely reachable are published — a search result
that leads nowhere would break the drill's promise that everything clickable is
followable. Vendors that appear only in federal/nonprofit lanes (never paid
through the state checkbook) are reachable through those lanes' own pages, not
here.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from ..config import Settings
from ..publish.envelope import envelope
from ..sources import SourceConfig
from ..storage import Storage, read_manifest, write_manifest
from .csv_download import QualityGateError
from .entities import _read

# Sankey program-area label -> agency page code, mirroring the site's
# AGENCY_PAGE_FOR_NODE. An agency not listed here is reached through the "Other"
# program-area block, so its area label is simply "Other".
_PAGE_AREA: dict[str, str] = {
    "4000": "Health and Human Services",
    "6010": "K-12 Education",
    "6013": "Higher Education",
    "5210": "Corrections and Rehabilitation",
}


def run_search_index(storage: Storage, cfg: SourceConfig, settings: Settings) -> str:
    now = datetime.now(UTC)
    as_of = now.strftime("%Y-%m-%dT%H%M%SZ")
    manifest = read_manifest(storage, cfg.source)

    vp = _read(storage, "published/vendor_profiles.json")
    wf = _read(storage, "published/budget_waterfall.json")
    ents = _read(storage, "published/entities.json")
    if not vp or not wf:
        raise QualityGateError(f"{cfg.source}: vendor_profiles or budget_waterfall not published")

    # an agency is reachable in the drill iff it has a dedicated page OR the
    # "Other" block lists it (that list is the waterfall's own agencies)
    reachable_agency = set(_PAGE_AREA) | {a["org_cd"] for a in wf["data"]["agencies"]}
    # defensively confirm the agency actually has a published vendors file —
    # the drill can't render a checkbook we never wrote
    vendors_file: dict[str, bool] = {}

    def has_vendors_file(cd: str) -> bool:
        if cd not in vendors_file:
            vendors_file[cd] = _read(storage, f"published/vendors/{cd}.json") is not None
        return vendors_file[cd]

    name_index = ents["data"]["name_index"] if ents else {}
    entities = ents["data"]["entities"] if ents else {}

    entries: list[dict[str, Any]] = []
    unreachable = 0
    for name, p in vp["data"]["vendors"].items():
        if p.get("public_sector") or p.get("masked"):
            continue
        # pick the largest-paying department whose drill path actually resolves
        best = None
        for d in p.get("departments", []):
            cd = d.get("agency_cd")
            if not cd or cd not in reachable_agency or not has_vendors_file(cd):
                continue
            if best is None or d["usd"] > best["usd"]:
                best = d
        if best is None:
            unreachable += 1
            continue
        key = name_index.get(name.upper())
        ent = entities.get(key) if key else None
        entries.append(
            {
                "name": name,
                "total_usd": round(p["total_usd"]),
                "area": _PAGE_AREA.get(best["agency_cd"], "Other"),
                "agency_cd": best["agency_cd"],
                "dept_org_cd": best["org_cd"],
                # a dossier panel appears only for orgs unified across 2+ lanes
                "dossier": bool(ent and ent.get("lane_count", 0) >= 2),
            }
        )

    entries.sort(key=lambda e: e["total_usd"], reverse=True)
    doc = {
        "vendor_count": len(entries),
        "vendors_unreachable": unreachable,
        "dossier_count": sum(1 for e in entries if e["dossier"]),
        "vendors": entries,
    }
    if doc["vendor_count"] < cfg.min_rows:
        raise QualityGateError(f"{cfg.source}: only {doc['vendor_count']} searchable vendors")

    blob = json.dumps(doc, sort_keys=True, default=str).encode()
    content_hash = hashlib.sha256(blob).hexdigest()
    if manifest.get("content_hash") == content_hash:
        manifest["checked_at"] = now.isoformat()
        write_manifest(storage, cfg.source, manifest)
        print(f"{cfg.source}: unchanged, no-op")
        return manifest["published_key"]

    key = "published/search_index.json"
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
            "row_count": doc["vendor_count"],
            "as_of": as_of,
            "ingested_at": now.isoformat(),
            "checked_at": now.isoformat(),
            "published_key": key,
        },
    )
    print(
        f"{cfg.source}: {doc['vendor_count']} searchable vendors "
        f"({doc['dossier_count']} with a cross-source dossier) -> {key}"
    )
    return key

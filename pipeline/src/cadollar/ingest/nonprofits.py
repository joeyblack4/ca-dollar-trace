"""Nonprofit enrichment: registry status + 990 financials for trail-end orgs.

Loads the AG charity registry (both the in-good-standing and the
delinquent/suspended lists), matches it by normalized name against the
entities already published on the site (grant recipients, BHCIP
organizations, top checkbook vendors), and fetches 990 financials from
ProPublica for the biggest matches. Every figure keeps its own provenance.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import UTC, datetime
from typing import Any

from ..config import Settings
from ..publish.envelope import envelope
from ..sources import SourceConfig
from ..storage import Storage, read_manifest, write_manifest
from .csv_download import QualityGateError
from .fiscal_vendor import PUBLIC_SECTOR_EXCEPTIONS_REGEX, PUBLIC_SECTOR_REGEX
from .http import fetch_bytes

PROPUBLICA_LOOKUPS = 60  # courtesy cap per run

SUFFIXES = r"\b(INC|INCORPORATED|LLC|CORP|CORPORATION|FOUNDATION|FDN|THE)\b"


def _norm(name: str) -> str:
    n = name.upper().strip()
    for ch in (".", ",", "'", "’", "(", ")", "-", "/", "&"):
        n = n.replace(ch, " ")
    n = re.sub(SUFFIXES, "", n)
    return " ".join(n.split())


def _load_registry(body: bytes, may_operate: bool) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    text = body.decode("utf-8", errors="replace")
    for row in csv.DictReader(io.StringIO(text)):
        name = (row.get("Name") or "").strip()
        if not name:
            continue
        key = _norm(name)
        rec = {
            "registered_name": " ".join(name.split()),
            "registry_status": (row.get("Registry Status") or "").strip(),
            "ct_number": (row.get("State Charity Reg#") or "").strip(),
            "fein": (row.get("FEIN") or "").strip(),
            "city": (row.get("City") or "").strip(),
            "may_operate": may_operate,
        }
        # prefer in-good-standing records on name collisions
        if key not in out or (may_operate and not out[key]["may_operate"]):
            out[key] = rec
    return out


_PUB = re.compile(PUBLIC_SECTOR_REGEX)
_PUB_EXC = re.compile(PUBLIC_SECTOR_EXCEPTIONS_REGEX)


def _is_public_sector(name: str) -> bool:
    u = name.upper()
    return bool(_PUB.search(u)) and not _PUB_EXC.search(u)


def _site_entities(storage: Storage) -> dict[str, str]:
    """normalized name -> display name for every trail-end entity on the site.

    Public agencies are excluded — they are not charities, and name collisions
    with the registry ("Lake County ...") would smear compliance flags onto
    governments."""
    entities: dict[str, str] = {}

    def read(key: str) -> dict | None:
        raw = storage.get_bytes(key)
        if raw is None:
            from ..config import REPO_ROOT

            p = REPO_ROOT / "site" / "public" / "data" / key.removeprefix("published/")
            raw = p.read_bytes() if p.exists() else None
        return json.loads(raw) if raw else None

    ga = read("published/grants_awards.json")
    if ga:
        for r in ga["data"]["top_recipients"]:
            if (r.get("recipient_type") or "").strip().lower() == "public agency":
                continue
            if not _is_public_sector(r["recipient_name"]):
                entities[_norm(r["recipient_name"])] = r["recipient_name"]
    bh = read("published/bhcip_awards.json")
    if bh:
        for e in bh["data"]["entities"]:
            if not _is_public_sector(e["name"]):
                entities[_norm(e["name"])] = e["name"]
    vp = read("published/vendor_profiles.json")
    if vp:
        for name, p in vp["data"]["vendors"].items():
            if not p.get("public_sector") and not p.get("masked") and not _is_public_sector(name):
                entities[_norm(name)] = name
    return entities


def run_nonprofits(storage: Storage, cfg: SourceConfig, settings: Settings) -> str:
    now = datetime.now(UTC)
    as_of = now.strftime("%Y-%m-%dT%H%M%SZ")
    manifest = read_manifest(storage, cfg.source)

    ok_body = fetch_bytes(cfg.endpoints["may_operate"], timeout_seconds=300)
    bad_body = fetch_bytes(cfg.endpoints["may_not_operate"], timeout_seconds=300)

    content_hash = hashlib.sha256(ok_body + bad_body).hexdigest()
    if manifest.get("content_hash") == content_hash:
        manifest["checked_at"] = now.isoformat()
        write_manifest(storage, cfg.source, manifest)
        print(f"{cfg.source}: unchanged upstream, no-op")
        return manifest["published_key"]

    storage.put_bytes(
        f"raw/{cfg.source}/{cfg.dataset}/{as_of}/may_operate.csv", ok_body, "text/csv"
    )
    storage.put_bytes(
        f"raw/{cfg.source}/{cfg.dataset}/{as_of}/may_not_operate.csv", bad_body, "text/csv"
    )

    registry = _load_registry(bad_body, may_operate=False)
    registry.update(_load_registry(ok_body, may_operate=True))
    if len(registry) < cfg.min_rows:
        raise QualityGateError(f"{cfg.source}: registry only has {len(registry)} rows")

    entities = _site_entities(storage)
    matches: dict[str, dict[str, Any]] = {}
    for key, display in entities.items():
        rec = registry.get(key)
        if rec:
            matches[display] = dict(rec)

    # 990 financials for the largest matched orgs with a usable FEIN
    looked_up = 0
    for display, rec in matches.items():
        if looked_up >= PROPUBLICA_LOOKUPS:
            break
        ein = re.sub(r"\D", "", rec.get("fein") or "")
        if len(ein) != 9:
            continue
        try:
            pp = json.loads(
                fetch_bytes(cfg.endpoints["propublica"].format(ein=ein), timeout_seconds=60)
            )
        except Exception:
            continue  # enrichment is best-effort; the registry facts still publish
        org = pp.get("organization") or {}
        filings = pp.get("filings_with_data") or []
        latest = filings[0] if filings else None
        rec["irs_990"] = {
            "propublica_url": f"https://projects.propublica.org/nonprofits/organizations/{ein}",
            "latest_filing_year": latest.get("tax_prd_yr") if latest else None,
            "total_revenue_usd": latest.get("totrevenue") if latest else None,
            "total_expenses_usd": latest.get("totfuncexpns") if latest else None,
            "ntee": org.get("ntee_code"),
        }
        looked_up += 1

    doc = {
        "registry_org_count": len(registry),
        "site_entities_checked": len(entities),
        "matched": len(matches),
        "match_rate_pct": round(100 * len(matches) / max(1, len(entities)), 1),
        "with_990": looked_up,
        "not_in_good_standing": sorted(
            d for d, r in matches.items() if not r["may_operate"]
        ),
        "organizations": matches,
    }

    key = "published/nonprofits.json"
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
            "row_count": len(registry),
            "as_of": as_of,
            "ingested_at": now.isoformat(),
            "checked_at": now.isoformat(),
            "published_key": key,
        },
    )
    print(
        f"{cfg.source}: {len(matches)}/{len(entities)} site entities matched, "
        f"{looked_up} with 990s -> {key}"
    )
    return key

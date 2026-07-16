"""SACS K-12: district finances from CDE's Data Viewer rollup export.

Finds the latest published statewide unaudited-actuals artifact (walking back
from the current fiscal year), downloads its ZIP only when the artifact id or
publish date changes, decodes each LEA's SACS account rows (fund + object
class), joins district names from the CDE directory, and publishes district
finances with object-class splits. SACS carries no vendor names — the lane's
terminator is structural, not a parsing shortfall.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..config import Settings
from ..publish.envelope import envelope
from ..sources import SourceConfig
from ..storage import Storage, read_manifest, write_manifest
from .csv_download import QualityGateError
from .http import fetch_bytes, fetch_json_post

STATEWIDE_CDS = "99000000000000"

# Operating-spend classes (objects 1000-6999). Objects 7000+ are transfers
# and pass-throughs: counting them double-counts money that re-appears as
# another entity's spending, so they are excluded from headline figures and
# disclosed separately.
OBJECT_CLASSES = [
    (1000, 1999, "Teacher salaries"),
    (2000, 2999, "Other staff salaries"),
    (3000, 3999, "Employee benefits"),
    (4000, 4999, "Books & supplies"),
    (5000, 5999, "Services & operating (outside providers)"),
    (6000, 6999, "Buildings & equipment"),
]


def _artifact_meta(cfg: SourceConfig, fy: str) -> dict[str, Any] | None:
    body = {
        "request": {
            "fullFiscalYear": fy,
            "reportingPeriod": "A",
            "cdsCode": STATEWIDE_CDS,
            "includeArtifactTypes": ["Import"],
        },
        "runMode": None,
        "testRunId": None,
        "timeZoneId": "America/Los_Angeles",
    }
    resp = json.loads(fetch_json_post(cfg.endpoints["rollup_meta"], body))
    r = resp.get("response") or {}
    return r if r.get("hasValue") and r.get("published") else None


def run_sacs(storage: Storage, cfg: SourceConfig, settings: Settings) -> str:
    now = datetime.now(UTC)
    as_of = now.strftime("%Y-%m-%dT%H%M%SZ")
    manifest = read_manifest(storage, cfg.source)

    # walk back from the current CA fiscal year to the latest published UA
    year = now.year if now.month >= 7 else now.year - 1
    meta = None
    for y in range(year, year - 4, -1):
        fy = f"{y}-{str(y + 1)[2:]}"
        meta = _artifact_meta(cfg, fy)
        if meta:
            break
    if not meta:
        raise QualityGateError(f"{cfg.source}: no published statewide rollup in last 4 FYs")

    content_hash = hashlib.sha256(
        f"{meta['id']}|{meta['date']}".encode()
    ).hexdigest()
    if manifest.get("content_hash") == content_hash:
        manifest["checked_at"] = now.isoformat()
        write_manifest(storage, cfg.source, manifest)
        print(f"{cfg.source}: artifact unchanged ({meta['fullFiscalYear']}), no-op")
        return manifest["published_key"]

    blob = fetch_bytes(
        cfg.endpoints["rollup_blob"].format(artifact_id=meta["id"]), timeout_seconds=600
    )
    storage.put_bytes(
        f"raw/{cfg.source}/{cfg.dataset}/{as_of}/{meta['fileName']}", blob, "application/zip"
    )
    directory = fetch_bytes(cfg.endpoints["directory"], timeout_seconds=300)

    doc, lea_count = build_k12_doc(blob, directory, meta)
    if lea_count < cfg.min_rows:
        raise QualityGateError(f"{cfg.source}: only {lea_count} LEA files in rollup")

    key = "published/k12_finances.json"
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
            "row_count": lea_count,
            "as_of": as_of,
            "ingested_at": now.isoformat(),
            "checked_at": now.isoformat(),
            "published_key": key,
        },
    )
    print(f"{cfg.source}: {lea_count} LEAs ({meta['fullFiscalYear']}) -> {key}")
    return key


def _district_names(directory_tsv: bytes) -> dict[str, dict[str, str]]:
    """Exact CDS(14) -> {name, county}. Charters resolve to their school name;
    district-level records use the district name."""
    names: dict[str, dict[str, str]] = {}
    text = directory_tsv.decode("utf-8", errors="replace")
    for row in csv.DictReader(io.StringIO(text), delimiter="\t"):
        cds = (row.get("CDSCode") or "").strip()
        if len(cds) != 14:
            continue
        school = (row.get("School") or "").strip()
        district = (row.get("District") or "").strip()
        names[cds] = {
            "name": school if school and school.lower() != "no data" else district,
            "county": (row.get("County") or "").strip(),
        }
    return names


def build_k12_doc(
    zip_bytes: bytes, directory_tsv: bytes, meta: dict[str, Any]
) -> tuple[dict[str, Any], int]:
    names = _district_names(directory_tsv)
    target_fy = meta["fullFiscalYear"]

    header_re = re.compile(r'^"(20[0-9-]{5})","(\d{14})","([^"]*)","([^"]*)"')
    row_re = re.compile(r'^"([^"]{19})","([^"]*)","I"')

    spend: dict[str, float] = {}
    revenue: dict[str, float] = {}
    classes: dict[str, dict[str, float]] = {}
    transfers: dict[str, float] = {}
    other_funds: dict[str, float] = {}
    unparsed: dict[str, int] = {}
    other_year_rows = 0

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        members = [m for m in z.namelist() if m.endswith(".dat")]
        for member in members:
            base = Path(member).name
            cds = base[0:2] + base[3:8] + base[9:16]
            in_target = False
            with z.open(member) as fh:
                for raw_line in io.TextIOWrapper(fh, encoding="utf-8", errors="replace"):
                    h = header_re.match(raw_line)
                    if h:
                        # files interleave sections: the target FY's actuals
                        # ("BA") with NEXT year's adopted budget ("BB") — only
                        # the target fiscal year's rows may count
                        in_target = h.group(1) == target_fy
                        continue
                    if not in_target:
                        if row_re.match(raw_line):
                            other_year_rows += 1
                        continue
                    m = row_re.match(raw_line)
                    if not m:
                        continue
                    acct, amt = m.groups()
                    try:
                        v = float(amt)
                    except ValueError:
                        unparsed[cds] = unparsed.get(cds, 0) + 1
                        continue
                    obj_s = acct[15:19]
                    if not obj_s.isdigit():
                        continue
                    obj = int(obj_s)
                    fund = acct[0:2]
                    if 7000 <= obj <= 7999:
                        transfers[cds] = transfers.get(cds, 0.0) + v
                    elif 1000 <= obj <= 6999:
                        if fund == "01":
                            spend[cds] = spend.get(cds, 0.0) + v
                            for lo, hi, label in OBJECT_CLASSES:
                                if lo <= obj <= hi:
                                    classes.setdefault(cds, {})[label] = (
                                        classes.get(cds, {}).get(label, 0.0) + v
                                    )
                                    break
                        else:
                            other_funds[cds] = other_funds.get(cds, 0.0) + v
                    elif 8000 <= obj <= 8999 and fund == "01":
                        revenue[cds] = revenue.get(cds, 0.0) + v
    lea_count = len(members)

    all_cds = set(spend) | set(revenue) | set(transfers) | set(other_funds)
    by_lea = []
    named = unmatched_names = 0
    for cds in all_cds:
        info = names.get(cds)
        if info:
            named += 1
        else:
            unmatched_names += 1
        cls = sorted(
            ({"object_class": k, "usd": v} for k, v in classes.get(cds, {}).items()),
            key=lambda x: -x["usd"],
        )
        by_lea.append(
            {
                "cds": cds,
                "district": info["name"] if info else None,
                "county": info["county"] if info else None,
                "spend_usd": spend.get(cds),
                "revenue_usd": revenue.get(cds),
                "transfers_passthrough_usd": transfers.get(cds),
                "other_funds_spend_usd": other_funds.get(cds),
                "unparsed": unparsed.get(cds, 0),
                "spend_by_class": cls,
            }
        )
    by_lea.sort(key=lambda x: -(x["spend_usd"] or 0))

    statewide_classes: dict[str, float] = {}
    for c in classes.values():
        for k, v in c.items():
            statewide_classes[k] = statewide_classes.get(k, 0.0) + v
    statewide = sorted(
        ({"object_class": k, "usd": v} for k, v in statewide_classes.items()),
        key=lambda x: -x["usd"],
    )

    top = by_lea[:60]
    rest = by_lea[60:]
    doc = {
        "fiscal_year": target_fy,
        "artifact_published": meta["date"],
        "lea_count": len(by_lea),
        "statewide_spend_usd": sum(x["spend_usd"] or 0 for x in by_lea),
        "scope_note": (
            "General Fund operating spending for the stated fiscal year only"
            " (each district file also carries next year's budget, which is"
            " excluded). Transfers/pass-throughs and non-General funds are"
            " reported separately — they double-count across entities."
        ),
        "next_year_budget_rows_excluded": other_year_rows,
        "statewide_by_class": statewide,
        "districts_published": len(top),
        "districts_not_shown": len(rest),
        "districts_not_shown_spend_usd": sum(x["spend_usd"] or 0 for x in rest),
        "district_names_unmatched": unmatched_names,
        "districts": top,
    }
    return doc, lea_count

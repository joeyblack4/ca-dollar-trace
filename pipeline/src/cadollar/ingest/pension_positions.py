"""CalPERS funding positions: each local government's pension debt.

Latest fiscal year per employer, aggregated across plan categories
(miscellaneous/safety/...). Employer names arrive inverted ("Alameda, City
of") and are normalized to a type + plain name so the /local tables can join
deterministically. Governments with independent retirement systems (LA city &
county, SF, ~20 county systems) are absent from CalPERS data — the published
caveat says so, and absence stays absent.
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
from .http import fetch_bytes


def _num(s: str | None) -> float:
    try:
        return float((s or "").replace(",", "") or 0)
    except ValueError:
        return 0.0


def _split_name(raw: str) -> tuple[str, str]:
    """'Alameda, City of' -> ('city', 'Alameda'); unmatched -> ('district', raw)."""
    m = re.match(r"^(.*),\s*(City|County|Town) of$", raw.strip(), re.IGNORECASE)
    if m:
        kind = m.group(2).lower()
        return ("city" if kind == "town" else kind), m.group(1).strip()
    return "district", raw.strip()


def run_pension_positions(storage: Storage, cfg: SourceConfig, settings: Settings) -> str:
    now = datetime.now(UTC)
    as_of = now.strftime("%Y-%m-%dT%H%M%SZ")
    manifest = read_manifest(storage, cfg.source)

    blob = fetch_bytes(cfg.download_url)
    content_hash = hashlib.sha256(blob).hexdigest()
    if manifest.get("content_hash") == content_hash:
        manifest["checked_at"] = now.isoformat()
        write_manifest(storage, cfg.source, manifest)
        print(f"{cfg.source}: unchanged, no-op")
        return manifest["published_key"]

    rows = list(csv.DictReader(io.StringIO(blob.decode("utf-8-sig"))))
    if not rows:
        raise QualityGateError(f"{cfg.source}: empty CSV")
    latest = max(r["Fiscal Year"] for r in rows)
    agencies: dict[str, dict[str, Any]] = {}
    for r in rows:
        if r["Fiscal Year"] != latest:
            continue
        kind, name = _split_name(r["Employer Name"])
        key = f"{kind}:{name.upper()}"
        a = agencies.setdefault(
            key,
            {
                "name": name, "kind": kind, "employer_name": r["Employer Name"].strip(),
                "liabilities_usd": 0.0, "assets_usd": 0.0, "unfunded_usd": 0.0,
                "plan_count": 0,
            },
        )
        a["liabilities_usd"] += _num(r["Actuarial Liabilities"])
        a["assets_usd"] += _num(r["Market Value of Assets"])
        a["unfunded_usd"] += _num(r["Unfunded Liabilities"])
        a["plan_count"] += 1
    for a in agencies.values():
        a["funded_pct"] = (
            round(a["assets_usd"] / a["liabilities_usd"] * 100, 1)
            if a["liabilities_usd"] > 0
            else None
        )
        for k in ("liabilities_usd", "assets_usd", "unfunded_usd"):
            a[k] = round(a[k])

    if len(agencies) < cfg.min_rows:
        raise QualityGateError(f"{cfg.source}: only {len(agencies)} agencies for FY{latest}")

    doc = {
        "fiscal_year": latest,
        "agency_count": len(agencies),
        "total_liabilities_usd": sum(a["liabilities_usd"] for a in agencies.values()),
        "total_assets_usd": sum(a["assets_usd"] for a in agencies.values()),
        "total_unfunded_usd": sum(a["unfunded_usd"] for a in agencies.values()),
        "by_kind": {
            k: sum(1 for a in agencies.values() if a["kind"] == k)
            for k in ("city", "county", "district")
        },
        "agencies": agencies,
    }

    key = "published/pension_positions.json"
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
            "row_count": len(agencies),
            "as_of": as_of,
            "ingested_at": now.isoformat(),
            "checked_at": now.isoformat(),
            "published_key": key,
        },
    )
    print(
        f"{cfg.source}: {len(agencies)} agencies FY{latest}, "
        f"${doc['total_unfunded_usd'] / 1e9:.1f}B unfunded -> {key}"
    )
    return key

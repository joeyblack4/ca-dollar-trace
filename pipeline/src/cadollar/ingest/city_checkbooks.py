"""LA + SF vendor checkbooks: the proof-of-possibility layer.

All aggregation happens server-side in Socrata (no bulk pull): LA's latest
complete fiscal year of payment transactions; SF's cumulative payments per
prime contractor. Published as one document with the two cities clearly
separated — their measures are not comparable and are never blended.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from ..config import Settings
from ..publish.envelope import envelope
from ..sources import SourceConfig
from ..storage import Storage, read_manifest, write_manifest
from .csv_download import QualityGateError
from .http import fetch_bytes


def _soda(base: str, query: str) -> list[dict[str, Any]]:
    return json.loads(fetch_bytes(base + quote(query, safe="?&=$'(),*"), timeout_seconds=300))


def run_city_checkbooks(storage: Storage, cfg: SourceConfig, settings: Settings) -> str:
    now = datetime.now(UTC)
    as_of = now.strftime("%Y-%m-%dT%H%M%SZ")
    manifest = read_manifest(storage, cfg.source)
    la, sf = cfg.endpoints["la"], cfg.endpoints["sf"]

    # --- LA: latest COMPLETE fiscal year (max year is in progress) ---
    (maxfy_row,) = _soda(la, "?$select=max(fiscal_year) as fy")
    la_fy = int(maxfy_row["fy"]) - 1
    (la_total,) = _soda(
        la, f"?$select=sum(dollar_amount) as usd,count(*) as n&$where=fiscal_year='{la_fy}'"
    )
    la_depts = _soda(
        la,
        f"?$select=department_name,sum(dollar_amount) as usd&$where=fiscal_year='{la_fy}'"
        "&$group=department_name&$order=usd DESC&$limit=20",
    )
    la_vendors = _soda(
        la,
        f"?$select=vendor_name,sum(dollar_amount) as usd&$where=fiscal_year='{la_fy}'"
        "&$group=vendor_name&$order=usd DESC&$limit=100",
    )

    # --- SF: cumulative payments per prime contractor ---
    (sf_total,) = _soda(sf, "?$select=sum(pmt_amt) as usd,count(*) as n,max(data_as_of) as asof")
    sf_vendors = _soda(
        sf,
        "?$select=prime_contractor,sum(pmt_amt) as paid&$group=prime_contractor"
        "&$order=paid DESC&$limit=100",
    )
    sf_depts = _soda(
        sf,
        "?$select=department,sum(pmt_amt) as paid&$group=department&$order=paid DESC&$limit=20",
    )

    if len(la_vendors) < cfg.min_rows or len(sf_vendors) < cfg.min_rows:
        raise QualityGateError(f"{cfg.source}: top-vendor lists came back short")

    doc = {
        "los_angeles": {
            "measure": "payment transactions",
            "fiscal_year": f"{la_fy - 1}-{str(la_fy)[2:]}",
            "total_usd": float(la_total["usd"]),
            "transaction_count": int(la_total["n"]),
            "by_department": [
                {"department": d["department_name"], "usd": float(d["usd"])} for d in la_depts
            ],
            "top_vendors": [
                {"name": v["vendor_name"], "usd": float(v["usd"])} for v in la_vendors
            ],
            "source_url": "https://controllerdata.lacity.org/",
        },
        "san_francisco": {
            "measure": "cumulative payments on contracts in the current system",
            "data_as_of": sf_total.get("asof"),
            "total_usd": float(sf_total["usd"]),
            "contract_count": int(sf_total["n"]),
            "by_department": [
                {"department": d["department"], "usd": float(d["paid"])} for d in sf_depts
            ],
            "top_vendors": [
                {"name": v["prime_contractor"], "usd": float(v["paid"])} for v in sf_vendors
            ],
            "source_url": "https://data.sfgov.org/",
        },
    }

    blob = json.dumps(doc, sort_keys=True).encode()
    content_hash = hashlib.sha256(blob).hexdigest()
    if manifest.get("content_hash") == content_hash:
        manifest["checked_at"] = now.isoformat()
        write_manifest(storage, cfg.source, manifest)
        print(f"{cfg.source}: unchanged upstream, no-op")
        return manifest["published_key"]

    storage.put_bytes(
        f"raw/{cfg.source}/{cfg.dataset}/{as_of}/aggregates.json", blob, "application/json"
    )
    key = "published/city_checkbooks.json"
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
            "row_count": len(la_vendors) + len(sf_vendors),
            "as_of": as_of,
            "ingested_at": now.isoformat(),
            "checked_at": now.isoformat(),
            "published_key": key,
        },
    )
    print(f"{cfg.source}: published {key}")
    return key

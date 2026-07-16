"""Federal subawards: the named pass-through edges inside California."""

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
from .http import fetch_json_post

FY = [{"start_date": "2024-10-01", "end_date": "2025-09-30"}]
CA = [{"country": "USA", "state": "CA"}]
FIELDS = [
    "Sub-Award ID",
    "Sub-Awardee Name",
    "Sub-Award Amount",
    "Awarding Agency",
    "Prime Recipient Name",
    "Sub-Award Date",
]


def _page(cfg: SourceConfig, codes: list[str], page: int) -> list[dict[str, Any]]:
    body = {
        "subawards": True,
        "fields": FIELDS,
        "filters": {
            "time_period": FY,
            "place_of_performance_locations": CA,
            "award_type_codes": codes,
        },
        "order": "desc",
        "sort": "Sub-Award Amount",
        "limit": 100,
        "page": page,
    }
    return json.loads(fetch_json_post(cfg.endpoints["search"], body)).get("results", [])


def run_federal_subawards(storage: Storage, cfg: SourceConfig, settings: Settings) -> str:
    now = datetime.now(UTC)
    as_of = now.strftime("%Y-%m-%dT%H%M%SZ")
    manifest = read_manifest(storage, cfg.source)

    grants = _page(cfg, ["02", "03", "04", "05"], 1) + _page(cfg, ["02", "03", "04", "05"], 2)
    contracts = _page(cfg, ["A", "B", "C", "D"], 1)

    def edges(rows: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
        return [
            {
                "kind": kind,
                "prime": r.get("Prime Recipient Name"),
                "sub": r.get("Sub-Awardee Name"),
                "usd": float(r.get("Sub-Award Amount") or 0),
                "federal_agency": r.get("Awarding Agency"),
                "date": r.get("Sub-Award Date"),
            }
            for r in rows
        ]

    all_edges = edges(grants, "grant") + edges(contracts, "contract")
    if len(all_edges) < cfg.min_rows:
        raise QualityGateError(f"{cfg.source}: only {len(all_edges)} subaward edges")

    blob = json.dumps(all_edges, sort_keys=True).encode()
    content_hash = hashlib.sha256(blob).hexdigest()
    if manifest.get("content_hash") == content_hash:
        manifest["checked_at"] = now.isoformat()
        write_manifest(storage, cfg.source, manifest)
        print(f"{cfg.source}: unchanged upstream, no-op")
        return manifest["published_key"]

    storage.put_bytes(
        f"raw/{cfg.source}/{cfg.dataset}/{as_of}/edges.json", blob, "application/json"
    )

    # roll up: which primes pass the most through, and to whom
    by_prime: dict[str, dict[str, Any]] = {}
    for e in all_edges:
        p = by_prime.setdefault(
            e["prime"], {"prime": e["prime"], "total_usd": 0.0, "sub_count": 0, "top_subs": []}
        )
        p["total_usd"] += e["usd"]
        p["sub_count"] += 1
        p["top_subs"].append({"sub": e["sub"], "usd": e["usd"], "kind": e["kind"]})
    for p in by_prime.values():
        p["top_subs"] = sorted(p["top_subs"], key=lambda s: -s["usd"])[:10]

    doc = {
        "federal_fiscal_year": "2025",
        "edges_shown": len(all_edges),
        "note": "largest reported subawards (top pages by amount), not the universe",
        "largest_edges": sorted(all_edges, key=lambda e: -e["usd"])[:60],
        "by_prime_recipient": sorted(by_prime.values(), key=lambda p: -p["total_usd"])[:25],
    }

    key = "published/federal_subawards.json"
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
            "row_count": len(all_edges),
            "as_of": as_of,
            "ingested_at": now.isoformat(),
            "checked_at": now.isoformat(),
            "published_key": key,
        },
    )
    print(f"{cfg.source}: {len(all_edges)} edges -> {key}")
    return key

"""USAspending connector: who actually receives federal money in California.

Top recipients + awarding agencies for awards performed in CA, federal FY2025.
The 'MULTIPLE RECIPIENTS' aggregate (payments to individuals, masked for
privacy) is kept and labeled masked — it is a large, honest part of the story.
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
from .http import fetch_json_post

FY2025 = [{"start_date": "2024-10-01", "end_date": "2025-09-30"}]
CA_POP = [{"country": "USA", "state": "CA"}]


def _body(page: int, limit: int = 100) -> dict[str, Any]:
    return {
        "filters": {
            "time_period": FY2025,
            "place_of_performance_locations": CA_POP,
        },
        "limit": limit,
        "page": page,
    }


def run_usaspending(storage: Storage, cfg: SourceConfig, settings: Settings) -> str:
    now = datetime.now(UTC)
    as_of = now.strftime("%Y-%m-%dT%H%M%SZ")
    manifest = read_manifest(storage, cfg.source)

    recipient_pages = [
        json.loads(fetch_json_post(cfg.endpoints["recipients"], _body(page)))
        for page in (1, 2)
    ]
    agencies_raw = json.loads(
        fetch_json_post(cfg.endpoints["awarding_agencies"], _body(1, limit=25))
    )

    payload = {"recipients": recipient_pages, "awarding_agencies": agencies_raw}
    blob = json.dumps(payload, sort_keys=True).encode()
    content_hash = hashlib.sha256(blob).hexdigest()
    if manifest.get("content_hash") == content_hash:
        manifest["checked_at"] = now.isoformat()
        write_manifest(storage, cfg.source, manifest)
        print(f"{cfg.source}: unchanged upstream, no-op")
        return manifest["published_key"]

    storage.put_bytes(
        f"raw/{cfg.source}/{cfg.dataset}/{as_of}/response.json", blob, "application/json"
    )

    recipients = []
    for page in recipient_pages:
        for r in page.get("results", []):
            masked = r.get("recipient_id") is None
            recipients.append(
                {
                    "name": r["name"],
                    "amount_usd": r["amount"],
                    "uei": r.get("uei"),
                    "masked_aggregate": masked,
                    "coverage_flag": "masked" if masked else "traceable",
                }
            )
    if len(recipients) < cfg.min_rows:
        raise QualityGateError(f"{cfg.source}: only {len(recipients)} recipients returned")

    awarding = [
        {"name": a["name"], "amount_usd": a["amount"], "code": a.get("code")}
        for a in agencies_raw.get("results", [])
    ]

    doc = {
        "federal_fiscal_year": "2025",
        "total_top_recipients_usd": sum(r["amount_usd"] for r in recipients),
        "recipients": recipients,
        "awarding_agencies": awarding,
    }
    key = "published/federal_ca.json"
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
            "row_count": len(recipients),
            "as_of": as_of,
            "ingested_at": now.isoformat(),
            "checked_at": now.isoformat(),
            "published_key": key,
        },
    )
    print(f"{cfg.source}: {len(recipients)} recipients -> {key}")
    return key

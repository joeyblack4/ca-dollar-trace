"""BHCIP awardees: the first RECOVERED dark hop.

The state checkbook ends at AHP (DHCS's third-party administrator). AHP's own
program dashboard publishes who the money was re-granted to — 437 projects.
Tableau Public has no stable bulk endpoint, so the source is a curated
browser-captured snapshot (sources/curated/bhcip_awardees_snapshot.csv).

Re-capture procedure (when new rounds land):
  1. open the all-rounds dashboard, toolbar -> Download -> Data
  2. Summary table -> Download CSV (UTF-16 TSV)
  3. convert to UTF-8 CSV with headers entity_name,project_name,funding_round
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime

from ..config import Settings
from ..publish.envelope import envelope
from ..sources import SourceConfig
from ..storage import Storage, read_manifest, write_manifest
from .csv_download import QualityGateError

SNAPSHOT = "curated/bhcip_awardees_snapshot.csv"


def run_bhcip(storage: Storage, cfg: SourceConfig, settings: Settings) -> str:
    now = datetime.now(UTC)
    as_of = now.strftime("%Y-%m-%dT%H%M%SZ")
    manifest = read_manifest(storage, cfg.source)

    path = settings.sources_dir / SNAPSHOT
    raw = path.read_bytes()
    content_hash = hashlib.sha256(raw).hexdigest()
    if manifest.get("content_hash") == content_hash:
        manifest["checked_at"] = now.isoformat()
        write_manifest(storage, cfg.source, manifest)
        print(f"{cfg.source}: snapshot unchanged, no-op")
        return manifest["published_key"]

    rows = list(csv.DictReader(raw.decode().splitlines()))
    if len(rows) < cfg.min_rows:
        raise QualityGateError(f"{cfg.source}: snapshot has {len(rows)} rows < {cfg.min_rows}")

    storage.put_bytes(f"raw/{cfg.source}/{cfg.dataset}/{as_of}/snapshot.csv", raw, "text/csv")

    by_round = Counter(r["funding_round"] for r in rows)
    by_entity: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_entity[r["entity_name"]].append(
            {"project": r["project_name"], "round": r["funding_round"]}
        )

    doc = {
        "project_count": len(rows),
        "entity_count": len(by_entity),
        "by_round": [
            {"round": rnd, "project_count": n} for rnd, n in sorted(by_round.items())
        ],
        "entities": [
            {"name": name, "project_count": len(projects), "projects": projects}
            for name, projects in sorted(
                by_entity.items(), key=lambda kv: (-len(kv[1]), kv[0])
            )
        ],
        "administrator_vendor_names": ["ADVOCATES FOR HUMAN POTENTIAL"],
    }

    key = "published/bhcip_awards.json"
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
            "row_count": len(rows),
            "as_of": as_of,
            "ingested_at": now.isoformat(),
            "checked_at": now.isoformat(),
            "published_key": key,
        },
    )
    print(f"{cfg.source}: {len(rows)} projects / {len(by_entity)} entities -> {key}")
    return key

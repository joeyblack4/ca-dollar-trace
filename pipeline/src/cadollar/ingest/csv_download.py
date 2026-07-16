"""csv_download connector: full-snapshot CSV sources (Grants Portal, AG charity, …).

Flow per run:
  1. fetch CSV bytes
  2. sha256 vs manifest — unchanged content is a no-op (records checked_at only)
  3. archive exact raw bytes:   raw/{source}/{dataset}/{as_of}/data.csv
  4. hand off to the source's cleanse step (typed parquet + provenance columns)
  5. quality gates (min rows, max row-drop vs last run) — a failed gate aborts
     BEFORE anything is published, leaving the last-good outputs in place
  6. write manifest

as_of here is the retrieval timestamp (UTC); the source's own publication date,
when it exposes one, is carried inside the cleansed data.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from ..sources import SourceConfig
from ..storage import Storage, read_manifest, write_manifest
from .http import fetch_bytes


@dataclass
class IngestResult:
    source: str
    changed: bool
    as_of: str
    raw_key: str | None
    row_count: int | None


class QualityGateError(Exception):
    """A fail-honest gate tripped; nothing was published."""


def run_csv_ingest(
    storage: Storage,
    cfg: SourceConfig,
    cleanse,  # callable(raw_bytes, as_of, content_hash) -> (parquet_bytes, row_count)
) -> IngestResult:
    now = datetime.now(UTC)
    as_of = now.strftime("%Y-%m-%dT%H%M%SZ")
    manifest = read_manifest(storage, cfg.source)

    raw = fetch_bytes(cfg.download_url)
    content_hash = hashlib.sha256(raw).hexdigest()

    if manifest.get("content_hash") == content_hash:
        manifest["checked_at"] = now.isoformat()
        write_manifest(storage, cfg.source, manifest)
        return IngestResult(cfg.source, changed=False, as_of=as_of, raw_key=None, row_count=None)

    raw_key = f"raw/{cfg.source}/{cfg.dataset}/{as_of}/data.csv"
    storage.put_bytes(raw_key, raw, content_type="text/csv")

    parquet_bytes, row_count = cleanse(raw, as_of, content_hash)

    # --- fail-honest gates: abort before publishing anything -----------------
    if row_count < cfg.min_rows:
        raise QualityGateError(
            f"{cfg.source}: {row_count} rows < min_rows {cfg.min_rows}; keeping last-good outputs"
        )
    last_count = manifest.get("row_count")
    if last_count:
        drop_pct = 100.0 * (last_count - row_count) / last_count
        if drop_pct > cfg.max_row_drop_pct:
            raise QualityGateError(
                f"{cfg.source}: row count fell {drop_pct:.1f}% ({last_count} -> {row_count}), "
                f"over max_row_drop_pct {cfg.max_row_drop_pct}; keeping last-good outputs"
            )

    cleansed_key = f"cleansed/{cfg.source}/{cfg.dataset}.parquet"
    storage.put_bytes(cleansed_key, parquet_bytes, content_type="application/octet-stream")

    write_manifest(
        storage,
        cfg.source,
        {
            "content_hash": content_hash,
            "row_count": row_count,
            "as_of": as_of,
            "ingested_at": now.isoformat(),
            "checked_at": now.isoformat(),
            "raw_key": raw_key,
            "cleansed_key": cleansed_key,
        },
    )
    return IngestResult(cfg.source, changed=True, as_of=as_of, raw_key=raw_key, row_count=row_count)

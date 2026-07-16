"""Publish the grants summary JSON from the cleansed parquet.

Unknown amounts are counted and surfaced (`funds_unknown_count`) — they are
never folded into totals as zero.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import duckdb

from ..sources import SourceConfig
from ..storage import Storage, read_manifest
from .envelope import envelope

SUMMARY_SQL = """
SELECT
    status,
    count(*)                                        AS grant_count,
    sum(est_avail_funds_usd)                        AS est_avail_funds_known_usd,
    count(*) FILTER (est_avail_funds_usd IS NULL)   AS funds_unknown_count
FROM read_parquet(?)
GROUP BY status ORDER BY status;
"""

BY_CATEGORY_SQL = """
SELECT
    categories                                      AS category,
    count(*)                                        AS grant_count,
    sum(est_avail_funds_usd)                        AS est_avail_funds_known_usd,
    count(*) FILTER (est_avail_funds_usd IS NULL)   AS funds_unknown_count
FROM read_parquet(?)
WHERE status IN ('active', 'forecasted')
GROUP BY categories
ORDER BY est_avail_funds_known_usd DESC NULLS LAST;
"""


def publish_grants_summary(storage: Storage, cfg: SourceConfig) -> str:
    manifest = read_manifest(storage, cfg.source)
    cleansed_key = manifest.get("cleansed_key")
    if not cleansed_key:
        raise RuntimeError(f"{cfg.source}: no cleansed data in manifest; run ingest first")

    parquet = storage.get_bytes(cleansed_key)
    assert parquet is not None, f"manifest points at missing object {cleansed_key}"

    with tempfile.TemporaryDirectory() as td:
        pq = Path(td) / "cleansed.parquet"
        pq.write_bytes(parquet)
        conn = duckdb.connect(":memory:")
        totals = _rows(conn, SUMMARY_SQL, str(pq))
        by_category = _rows(conn, BY_CATEGORY_SQL, str(pq))
        conn.close()

    doc = envelope(
        cfg,
        as_of=manifest["as_of"],
        ingested_at=manifest["ingested_at"],
        data={"totals_by_status": totals, "open_by_category": by_category},
    )
    key = "published/grants_summary.json"
    storage.put_bytes(key, json.dumps(doc, indent=2, default=str).encode(), "application/json")
    return key


def _rows(conn: duckdb.DuckDBPyConnection, sql: str, pq_path: str) -> list[dict]:
    cur = conn.execute(sql, [pq_path])
    cols = [d[0] for d in cur.description]
    out = []
    for row in cur.fetchall():
        rec = dict(zip(cols, row))
        # DECIMAL -> float for JSON; None stays None (unknown, not zero)
        if rec.get("est_avail_funds_known_usd") is not None:
            rec["est_avail_funds_known_usd"] = float(rec["est_avail_funds_known_usd"])
        out.append(rec)
    return out

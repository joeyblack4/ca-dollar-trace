"""SCO ByTheNumbers county expenditures: the county lane, category-level.

SODA-paginated pull of FY >= fy_min, cleansed to parquet, published as one
document: every county's latest reported FY with total expenditures, top
categories, population, and per-capita figure — plus which counties lag.
The coverage flag is category_only by design: this is where the public
record thins out, and the product's job is to show that honestly.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import duckdb

from ..config import Settings
from ..publish.envelope import envelope
from ..sources import SourceConfig
from ..storage import Storage, read_manifest, write_manifest
from .csv_download import QualityGateError
from .http import fetch_bytes

PAGE = 50_000


def run_county_finances(storage: Storage, cfg: SourceConfig, settings: Settings) -> str:
    now = datetime.now(UTC)
    as_of = now.strftime("%Y-%m-%dT%H%M%SZ")
    manifest = read_manifest(storage, cfg.source)
    fy_min = int(cfg.extra.get("fy_min", 2020))

    pages: list[bytes] = []
    offset = 0
    while True:
        query = (
            f"?$where=fiscal_year >= '{fy_min}'"
            f"&$order=index&$limit={PAGE}&$offset={offset}"
        )
        body = fetch_bytes(cfg.endpoints["soda"] + quote(query, safe="?&=$'"))
        rows = json.loads(body)
        if not rows:
            break
        pages.append(body)
        offset += PAGE
        if len(rows) < PAGE:
            break

    row_total = sum(len(json.loads(p)) for p in pages)
    if row_total < cfg.min_rows:
        raise QualityGateError(f"{cfg.source}: only {row_total} rows >= FY{fy_min}")

    content_hash = hashlib.sha256(b"".join(pages)).hexdigest()
    if manifest.get("content_hash") == content_hash:
        manifest["checked_at"] = now.isoformat()
        write_manifest(storage, cfg.source, manifest)
        print(f"{cfg.source}: unchanged upstream, no-op")
        return manifest["published_key"]

    for i, p in enumerate(pages):
        storage.put_bytes(
            f"raw/{cfg.source}/{cfg.dataset}/{as_of}/page{i}.json", p, "application/json"
        )

    doc = build_county_doc(pages, storage)
    key = "published/county_finances.json"
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
            "row_count": row_total,
            "as_of": as_of,
            "ingested_at": now.isoformat(),
            "checked_at": now.isoformat(),
            "published_key": key,
        },
    )
    print(f"{cfg.source}: {row_total} rows -> {key}")
    return key


def build_county_doc(pages: list[bytes], storage: Storage) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as td:
        paths = []
        for i, p in enumerate(pages):
            fp = Path(td) / f"p{i}.json"
            fp.write_bytes(p)
            paths.append(str(fp))
        conn = duckdb.connect(":memory:")
        file_list = ", ".join(f"'{p}'" for p in paths)
        conn.execute(
            f"""
            CREATE TABLE county AS
            SELECT entity_name                            AS county,
                   TRY_CAST(fiscal_year AS INTEGER)       AS fiscal_year,
                   category,
                   TRY_CAST(values AS DOUBLE)             AS amount_usd,
                   TRY_CAST(estimated_population AS BIGINT) AS population
            FROM read_json_auto([{file_list}])
            """
        )

        counties = _rows(conn, """
            WITH latest AS (
                SELECT county, max(fiscal_year) AS fy FROM county GROUP BY 1
            )
            SELECT c.county,
                   l.fy                                   AS fiscal_year,
                   sum(c.amount_usd)                      AS total_usd,
                   any_value(c.population)                AS population,
                   count(*) FILTER (c.amount_usd IS NULL) AS amount_unparsed_count
            FROM county c JOIN latest l ON c.county = l.county AND c.fiscal_year = l.fy
            GROUP BY 1, 2 ORDER BY 3 DESC NULLS LAST""")

        cat_rows = _rows(conn, """
            WITH latest AS (
                SELECT county, max(fiscal_year) AS fy FROM county GROUP BY 1
            )
            SELECT c.county, c.category, sum(c.amount_usd) AS usd
            FROM county c JOIN latest l ON c.county = l.county AND c.fiscal_year = l.fy
            GROUP BY 1, 2""")
        conn.close()

    cats_by_county: dict[str, list[dict[str, Any]]] = {}
    for r in cat_rows:
        cats_by_county.setdefault(r["county"], []).append(
            {"category": r["category"], "usd": r["usd"]}
        )
    for c in counties:
        cats = sorted(
            (x for x in cats_by_county.get(c["county"], []) if x["usd"] is not None),
            key=lambda x: -x["usd"],
        )
        c["top_categories"] = cats[:8]
        c["category_count"] = len(cats)
        c["per_capita_usd"] = (
            round(c["total_usd"] / c["population"], 0)
            if c["total_usd"] and c["population"]
            else None
        )

    latest_fy = max(c["fiscal_year"] for c in counties)
    lagging = [c["county"] for c in counties if c["fiscal_year"] < latest_fy]
    return {
        "county_count": len(counties),
        "not_in_this_dataset": ["San Francisco (city-county; files through the cities dataset)"],
        "latest_fiscal_year": latest_fy,
        "counties_lagging_behind_latest_fy": lagging,
        "total_latest_usd": sum(c["total_usd"] or 0 for c in counties),
        "counties": counties,
    }


def _rows(conn: duckdb.DuckDBPyConnection, sql: str) -> list[dict[str, Any]]:
    cur = conn.execute(sql)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]

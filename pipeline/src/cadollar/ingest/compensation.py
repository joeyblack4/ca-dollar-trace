"""Government compensation: the payroll every checkbook excludes.

gcc.sco.ca.gov serves /RawExport/{year}_{type}.zip but its edge returns 403 to
scripted TLS handshakes while serving real browsers, so the annual snapshots
are captured in a browser into sources/captured/. Aggregates position-level
records to employer totals (wages + employer benefit contribution) and keys
them to the entities the site already tracks — filling the "payroll excluded"
figure in the coverage meters.

Re-capture (once a year, when SCO posts the new year):
  open https://gcc.sco.ca.gov/Reports/RawExport.aspx in a browser, download
  {year}_StateDepartment.zip, {year}_County.zip, {year}_City.zip into
  sources/captured/, and bump `extra.year` + `extra.files` in the YAML.
"""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from ..config import Settings
from ..publish.envelope import envelope
from ..sources import SourceConfig
from ..storage import Storage, read_manifest, write_manifest
from .csv_download import QualityGateError

EMPLOYER_SQL = """
SELECT EmployerName                                       AS employer,
       count(*)                                           AS positions,
       sum(TRY_CAST(TotalWages AS DOUBLE))                AS wages_usd,
       sum(TRY_CAST(TotalRetirementAndHealthContribution AS DOUBLE)) AS benefits_usd,
       count(*) FILTER (TRY_CAST(TotalWages AS DOUBLE) IS NULL
                        AND TotalWages IS NOT NULL)       AS unparsed
FROM read_csv(?, header=true, all_varchar=true)
GROUP BY 1 ORDER BY 2 DESC
"""


def run_compensation(storage: Storage, cfg: SourceConfig, settings: Settings) -> str:
    now = datetime.now(UTC)
    as_of = now.strftime("%Y-%m-%dT%H%M%SZ")
    manifest = read_manifest(storage, cfg.source)
    captured = settings.sources_dir / "captured"
    files: dict[str, str] = cfg.extra.get("files", {})
    year = int(cfg.extra.get("year", 0))

    raw = {}
    for level, fname in sorted(files.items()):
        path = captured / fname
        if not path.exists():
            raise QualityGateError(f"{cfg.source}: captured file missing: {fname}")
        raw[level] = path.read_bytes()

    content_hash = hashlib.sha256(b"".join(raw[k] for k in sorted(raw))).hexdigest()
    if manifest.get("content_hash") == content_hash:
        manifest["checked_at"] = now.isoformat()
        write_manifest(storage, cfg.source, manifest)
        print(f"{cfg.source}: snapshot unchanged, no-op")
        return manifest["published_key"]

    doc, total_positions = _build(raw, year)
    if total_positions < cfg.min_rows:
        raise QualityGateError(f"{cfg.source}: only {total_positions} positions parsed")

    key = "published/compensation.json"
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
            "row_count": total_positions,
            "as_of": as_of,
            "ingested_at": now.isoformat(),
            "checked_at": now.isoformat(),
            "published_key": key,
        },
    )
    print(f"{cfg.source}: {total_positions:,} positions across {len(files)} levels -> {key}")
    return key


def _build(raw: dict[str, bytes], year: int) -> tuple[dict[str, Any], int]:
    conn = duckdb.connect(":memory:")
    levels: dict[str, dict[str, Any]] = {}
    total_positions = 0
    all_employers: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory() as td:
        for level, body in raw.items():
            with zipfile.ZipFile(io.BytesIO(body)) as z:
                csv_name = z.namelist()[0]
                z.extract(csv_name, td)
            p = str(Path(td) / csv_name)
            rows = _rows(conn, EMPLOYER_SQL, p)
            positions = sum(r["positions"] for r in rows)
            total_positions += positions
            for r in rows:
                r["level"] = level
                all_employers.append(r)
            levels[level] = {
                "employer_count": len(rows),
                "positions": positions,
                "wages_usd": sum(r["wages_usd"] or 0 for r in rows),
                "benefits_usd": sum(r["benefits_usd"] or 0 for r in rows),
                "unparsed": sum(r["unparsed"] for r in rows),
                "top_employers": sorted(
                    (
                        {
                            "employer": r["employer"],
                            "positions": r["positions"],
                            "wages_usd": r["wages_usd"],
                            "benefits_usd": r["benefits_usd"],
                        }
                        for r in rows
                    ),
                    key=lambda x: -((x["wages_usd"] or 0) + (x["benefits_usd"] or 0)),
                )[:40],
            }
    conn.close()

    # per-employer lookup for the coverage meters (normalized name -> comp)
    by_employer = {
        _norm(r["employer"]): {
            "level": r["level"],
            "positions": r["positions"],
            "wages_usd": r["wages_usd"] or 0,
            "benefits_usd": r["benefits_usd"] or 0,
        }
        for r in all_employers
    }

    doc = {
        "year": year,
        "levels": levels,
        "statewide_wages_usd": sum(lv["wages_usd"] for lv in levels.values()),
        "statewide_benefits_usd": sum(lv["benefits_usd"] for lv in levels.values()),
        "by_employer": by_employer,
    }
    return doc, total_positions


def _norm(name: str) -> str:
    return " ".join((name or "").upper().split())


def _rows(conn: duckdb.DuckDBPyConnection, sql: str, path: str) -> list[dict[str, Any]]:
    cur = conn.execute(sql, [path])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]

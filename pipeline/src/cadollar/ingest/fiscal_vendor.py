"""Open FI$Cal vendor transactions: the state checkbook, automated.

Catalog-driven and incremental: the pointer CSV lists every per-department,
per-FY file with an UploadDate — a file is (re)downloaded only when that
changes. Each CSV is cleansed to parquet, then aggregates are computed across
everything present and joined against enacted-budget department totals to
produce the checkbook-coverage percentage — the honest core number: how much
of each department's budget is visible as vendor payments at all.

Heavy source (multi-GB backfill): excluded from `run-all` (extra.heavy) and
run explicitly — `cadollar run fiscal_vendor` — from a machine with a
persistent data dir.
"""

from __future__ import annotations

import csv
import io
import json
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from ..config import Settings
from ..publish.envelope import envelope
from ..sources import SourceConfig
from ..storage import Storage, read_manifest, write_manifest
from .csv_download import QualityGateError
from .http import fetch_bytes

CLEANSE_SQL = """
CREATE OR REPLACE TABLE cleansed AS
SELECT
    business_unit,
    agency_name,
    department_name,
    VENDOR_NAME                                        AS vendor_name,
    upper(VENDOR_NAME) LIKE '%CONFIDENTIAL%'           AS is_confidential,
    TRY_CAST(accounting_date AS DATE)                  AS accounting_date,
    fiscal_year_begin,
    accounting_period,
    account_type, account_category, account_description,
    fund_code, fund_group, fund_description,
    program_code, program_description,
    TRY_CAST(monetary_amount AS DECIMAL(18,2))         AS amount_usd,
    ? AS _source_file, ? AS _upload_date, ? AS _ingested_at
FROM read_csv(?, header=true, all_varchar=true);
"""


def run_fiscal_vendor(
    storage: Storage, cfg: SourceConfig, settings: Settings, only_fy: list[int] | None = None
) -> str:
    now = datetime.now(UTC)
    manifest = read_manifest(storage, cfg.source)
    file_state: dict[str, Any] = manifest.get("files", {})

    catalog = _load_catalog(cfg)
    fy_min = int(cfg.extra.get("fy_min", 20))
    wanted = [
        row
        for row in catalog
        if (fy := _fy(row["FileName"])) is not None
        and fy >= fy_min
        and (only_fy is None or fy in only_fy)
    ]
    if len(wanted) < cfg.min_rows:
        raise QualityGateError(
            f"{cfg.source}: catalog lists only {len(wanted)} files >= FY{fy_min}"
        )

    fetched = skipped = 0
    for row in wanted:
        name = row["FileName"]
        state = file_state.get(name)
        if state and state.get("upload_date") == row["UploadDate"] and state.get(
            "file_size"
        ) == row["FileSize"]:
            skipped += 1
            continue
        file_state[name] = _ingest_file(storage, cfg, row, now)
        fetched += 1
        if fetched % 25 == 0:
            print(f"{cfg.source}: {fetched} files ingested...")
            # checkpoint so an interrupted backfill resumes where it stopped
            manifest["files"] = file_state
            write_manifest(storage, cfg.source, manifest)

    print(f"{cfg.source}: {fetched} fetched, {skipped} unchanged")

    key = publish_vendor_summaries(storage, cfg, settings, file_state, now)

    manifest.update(
        {
            "files": file_state,
            "row_count": len(file_state),
            "as_of": now.strftime("%Y-%m-%dT%H%M%SZ"),
            "ingested_at": now.isoformat(),
            "checked_at": now.isoformat(),
            "published_key": key,
        }
    )
    write_manifest(storage, cfg.source, manifest)
    return key


def _load_catalog(cfg: SourceConfig) -> list[dict[str, str]]:
    raw = fetch_bytes(cfg.download_url)
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))


def _fy(filename: str) -> int | None:
    m = re.search(r"_FY(\d\d)\.csv$", filename)
    return int(m.group(1)) if m else None


def _bu(filename: str) -> str:
    m = re.match(r"Vendor_(\d{4})_", filename)
    return m.group(1) if m else "0000"


def _ingest_file(
    storage: Storage, cfg: SourceConfig, row: dict[str, str], now: datetime
) -> dict[str, Any]:
    name, fy, bu = row["FileName"], _fy(row["FileName"]), _bu(row["FileName"])
    body = fetch_bytes(row["Download"], timeout_seconds=600)

    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "in.csv"
        out = Path(td) / "out.parquet"
        src.write_bytes(body)
        conn = duckdb.connect(":memory:")
        conn.execute(CLEANSE_SQL, [name, row["UploadDate"], now.isoformat(), str(src)])
        (rows,) = conn.execute("SELECT count(*) FROM cleansed").fetchone()
        (total,) = conn.execute("SELECT sum(amount_usd) FROM cleansed").fetchone()
        conn.execute(f"COPY cleansed TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)")
        conn.close()
        parquet_key = f"cleansed/fiscal_vendor/fy{fy}/{bu}.parquet"
        storage.put_file(parquet_key, out)

    return {
        "upload_date": row["UploadDate"],
        "file_size": row["FileSize"],
        "parquet_key": parquet_key,
        "rows": int(rows),
        "total_usd": float(total or 0),
        "business_unit": bu,
        "fy": fy,
    }


def publish_vendor_summaries(
    storage: Storage,
    cfg: SourceConfig,
    settings: Settings,
    file_state: dict[str, Any],
    now: datetime,
) -> str:
    """Aggregate all cleansed parquet -> per-agency vendor JSON + coverage overview."""
    glob_path = storage.local_path("cleansed/fiscal_vendor/*/*.parquet")
    if glob_path is None:
        raise NotImplementedError("fiscal_vendor aggregation currently requires local storage")

    dept_budget, dept_agency, dept_title = _budget_maps(storage)

    conn = duckdb.connect(":memory:")
    latest_fy = max((s["fy"] for s in file_state.values()), default=None)
    dept_rows = conn.execute(
        f"""
        SELECT business_unit,
               any_value(department_name),
               count(*),
               count(DISTINCT vendor_name),
               sum(amount_usd),
               sum(amount_usd) FILTER (is_confidential),
               min(accounting_date), max(accounting_date)
        FROM read_parquet('{glob_path}')
        WHERE fiscal_year_begin = '20{latest_fy}'
        GROUP BY 1
        """
    ).fetchall()

    by_agency: dict[str, list[dict[str, Any]]] = {}
    unmatched = []
    for bu, dname, txns, vendors, total, confid, dmin, dmax in dept_rows:
        top = conn.execute(
            f"""
            SELECT vendor_name, sum(amount_usd), bool_or(is_confidential)
            FROM read_parquet('{glob_path}')
            WHERE business_unit = ? AND fiscal_year_begin = '20{latest_fy}'
            GROUP BY 1 ORDER BY 2 DESC LIMIT 25
            """,
            [bu],
        ).fetchall()
        budget = dept_budget.get(bu)
        entry = {
            "org_cd": bu,
            "title": dept_title.get(bu, dname),
            "fiscal_year": f"20{latest_fy}-{latest_fy + 1}",
            "transactions": txns,
            "vendor_count": vendors,
            "vendor_total_usd": float(total or 0),
            "confidential_usd": float(confid or 0),
            "accounting_dates": [str(dmin), str(dmax)],
            "enacted_budget_usd": budget,
            "checkbook_coverage_pct": (
                round(100 * float(total or 0) / budget, 1) if budget else None
            ),
            "top_vendors": [
                {"name": v, "usd": float(a), "masked": bool(m)} for v, a, m in top
            ],
        }
        agency_cd = dept_agency.get(bu)
        if agency_cd:
            by_agency.setdefault(agency_cd, []).append(entry)
        else:
            unmatched.append(entry)
    conn.close()

    as_of = now.strftime("%Y-%m-%dT%H%M%SZ")
    for agency_cd, depts in by_agency.items():
        depts.sort(key=lambda d: -d["vendor_total_usd"])
        storage.put_bytes(
            f"published/vendors/{agency_cd}.json",
            json.dumps(
                envelope(
                    cfg,
                    as_of=as_of,
                    ingested_at=now.isoformat(),
                    data={"departments": depts},
                ),
                indent=2,
            ).encode(),
            "application/json",
        )

    overview = {
        "latest_fiscal_year": f"20{latest_fy}-{latest_fy + 1}" if latest_fy else None,
        "files_ingested": len(file_state),
        "departments_with_checkbook": len(dept_rows),
        "vendor_total_usd": sum(float(r[4] or 0) for r in dept_rows),
        "confidential_total_usd": sum(float(r[5] or 0) for r in dept_rows),
        "unmatched_business_units": [
            {"org_cd": e["org_cd"], "title": e["title"], "vendor_total_usd": e["vendor_total_usd"]}
            for e in unmatched
        ],
    }
    key = "published/checkbook_coverage.json"
    storage.put_bytes(
        key,
        json.dumps(
            envelope(cfg, as_of=as_of, ingested_at=now.isoformat(), data=overview), indent=2
        ).encode(),
        "application/json",
    )
    print(
        f"{cfg.source}: published {len(by_agency)} agency vendor files "
        f"({len(unmatched)} business units unmatched to budget agencies)"
    )
    return key


def _budget_maps(storage: Storage) -> tuple[dict, dict, dict]:
    """org_cd -> enacted all-funds budget / agency_cd / title, from ebudget_detail output."""
    budgets: dict[str, float] = {}
    agency_of: dict[str, str] = {}
    titles: dict[str, str] = {}
    raw = storage.get_bytes("published/budget_waterfall.json")
    agency_cds = (
        [a["org_cd"] for a in json.loads(raw)["data"]["agencies"]] if raw else []
    )
    for cd in agency_cds:
        doc = storage.get_bytes(f"published/agencies/{cd}.json")
        if not doc:
            continue
        for dept in json.loads(doc)["data"]["departments"]:
            budgets[dept["org_cd"]] = dept["total_usd"]
            agency_of[dept["org_cd"]] = cd
            titles[dept["org_cd"]] = dept["title"]
    return budgets, agency_of, titles

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

# Heuristic classifier: payees that are themselves government bodies (state
# departments, counties, cities, districts, public universities). These are
# transfers within the public sector, not purchases from outside vendors —
# mixing them changes what "who got paid" means. Published as a heuristic
# flag (`public_sector`), rule list kept here in the open; tested in
# tests/test_public_sector_regex.py against real vendor names.
PUBLIC_SECTOR_REGEX = (
    r"^(DEPT|DEPARTMENT) OF|"
    r"^STATE OF |^STATE (CONTROLLER|TREASURER|BAR)|"
    r"^(CA|CALIF|CALIFORNIA) (STATE|DEPT|DEPARTMENT|HIGHWAY|CONSERVATION)|"
    r"^COUNTY OF |COUNTY (OF[ ,]|TREASURER|OFFICE OF ED)|"
    r"\bCOUNTY (SUPERINTENDENT|BEHAVIORAL|HEALTH|SHERIFF|PROBATION)|"
    r"^CITY OF |CITY & COUNTY|^TOWN OF |"
    r"TREASURER OF |AUDITOR[- ]CONTROLLER|"
    r"^UNIVERSITY OF CALIFORNIA|^UC (REGENTS|DAVIS|LOS ANGELES|SAN|BERKELEY|IRVINE|RIVERSIDE)|"
    r"^REGENTS OF|CAL(IFORNIA)? STATE UNIV|^CSU |\bSTATE UNIVERSITY\b|"
    r"SCHOOL DIST|UNIFIED (SCHOOL|SD)|\bUSD$|COMMUNITY COLLEGE|"
    r"WATER DIST(RICT)?\b|IRRIGATION DIST(RICT)?\b|SANITATION DIST(RICT)?\b|"
    r"TRANSIT (DIST|AUTH)|METROPOLITAN TRANSPORTATION AUTH|"
    r"^JUDICIAL COUNCIL|^SUPERIOR COURT|"
    r"^OFFICE OF THE (GOVERNOR|PRESIDENT OF THE|ATTORNEY|SECRETARY|INSPECTOR|STATE)|"
    r"HOUSING AUTH|JOINT POWERS"
)

# Known private organizations whose names collide with the patterns above.
PUBLIC_SECTOR_EXCEPTIONS_REGEX = r"^CITY OF HOPE|WATER DISTRIBUT|SANITATION DISTRIBUT"

PUBLIC_SECTOR_SQL = (
    f"(regexp_matches(upper({{col}}), '{PUBLIC_SECTOR_REGEX}') "
    f"AND NOT regexp_matches(upper({{col}}), '{PUBLIC_SECTOR_EXCEPTIONS_REGEX}'))"
)

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
        if (
            state
            and state.get("upload_date") == row["UploadDate"]
            and state.get("file_size") == row["FileSize"]
            and storage.exists(state.get("parquet_key", ""))  # manifest may outlive data
        ):
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
    ps_dept = PUBLIC_SECTOR_SQL.format(col="t.vendor_name")
    ps_top = PUBLIC_SECTOR_SQL.format(col="any_value(vendor_name)")
    # per-department latest FY (departments upload on their own schedules; a
    # single global latest-FY filter would silently drop everyone who hasn't
    # posted the newest year yet)
    dept_rows = conn.execute(
        f"""
        WITH latest AS (
            SELECT business_unit, max(fiscal_year_begin) AS fy
            FROM read_parquet('{glob_path}') GROUP BY 1
        )
        SELECT t.business_unit,
               any_value(t.department_name),
               count(*),
               count(DISTINCT t.vendor_name),
               sum(t.amount_usd),
               sum(t.amount_usd) FILTER (t.is_confidential),
               min(t.accounting_date), max(t.accounting_date),
               sum(t.amount_usd) FILTER ({ps_dept}),
               sum(t.amount_usd) FILTER (t.account_description = 'SCO Inbound Interface Dept Exp'),
               count(*) FILTER (t.amount_usd IS NULL),
               any_value(t.fiscal_year_begin)
        FROM read_parquet('{glob_path}') t
        JOIN latest l ON t.business_unit = l.business_unit AND t.fiscal_year_begin = l.fy
        GROUP BY 1
        """
    ).fetchall()

    by_agency: dict[str, list[dict[str, Any]]] = {}
    unmatched = []
    for (
        bu, dname, txns, vendors, total, confid, dmin, dmax, pub_usd, sco_usd,
        unparsed, dept_fy,
    ) in dept_rows:
        fy_int = int(dept_fy)
        top = conn.execute(
            f"""
            SELECT vendor_name, sum(amount_usd), bool_or(is_confidential),
                   {ps_top},
                   sum(amount_usd) FILTER (amount_usd > 0)
            FROM read_parquet('{glob_path}')
            WHERE business_unit = ? AND fiscal_year_begin = ?
            GROUP BY 1 ORDER BY 2 DESC LIMIT 25
            """,
            [bu, dept_fy],
        ).fetchall()
        budget = dept_budget.get(bu)
        entry = {
            "org_cd": bu,
            "title": dept_title.get(bu, dname),
            "fiscal_year": f"{fy_int}-{(fy_int + 1) % 100:02d}",
            "transactions": txns,
            "vendor_count": vendors,
            "vendor_total_usd": float(total or 0),
            "confidential_usd": float(confid or 0),
            "public_sector_usd": float(pub_usd or 0),
            # net effect of account 5390950 (SCO-processed payments reclassified
            # after the fact) — usually negative; totals above are net of it
            "sco_interface_net_usd": float(sco_usd or 0),
            # fail-honest: rows whose amount could not be parsed are counted,
            # never silently dropped into the sums above
            "amount_unparsed_count": int(unparsed or 0),
            "accounting_dates": [str(dmin), str(dmax)],
            "enacted_budget_usd": budget,
            "checkbook_coverage_pct": (
                round(100 * float(total or 0) / budget, 1) if budget else None
            ),
            "top_vendors_limit": 25,
            "top_vendors": [
                {
                    "name": v,
                    "usd": float(a),
                    "masked": bool(m),
                    "public_sector": bool(psf),
                    # gross positives published when adjustments are material (>5%)
                    "gross_usd": (
                        float(g) if g and float(a) < float(g) * 0.95 else None
                    ),
                }
                for v, a, m, psf, g in top
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

    _publish_vendor_profiles(storage, cfg, conn_path=glob_path, now=now, dept_agency=dept_agency)

    latest_fy = max((s["fy"] for s in file_state.values()), default=None)
    overview = {
        "latest_fiscal_year": f"20{latest_fy}-{latest_fy + 1}" if latest_fy else None,
        "files_ingested": len(file_state),
        "departments_with_checkbook": len(dept_rows),
        "note": "department figures use each department's own latest available fiscal year",
        "vendor_total_usd": sum(float(r[4] or 0) for r in dept_rows),
        "confidential_total_usd": sum(float(r[5] or 0) for r in dept_rows),
        "amount_unparsed_total": sum(int(r[10] or 0) for r in dept_rows),
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


def _publish_vendor_profiles(
    storage: Storage,
    cfg: SourceConfig,
    conn_path: str,
    now: datetime,
    dept_agency: dict[str, str],
) -> None:
    """One compact file: the top-500 vendors by all-years total, each with
    per-year, per-department, and per-program breakdowns — the deepest drill
    level the checkbook supports."""
    conn = duckdb.connect(":memory:")
    top = conn.execute(
        f"""
        SELECT vendor_name, sum(amount_usd) total, bool_or(is_confidential),
               {PUBLIC_SECTOR_SQL.format(col="any_value(vendor_name)")}
        FROM read_parquet('{conn_path}')
        GROUP BY 1 ORDER BY 2 DESC LIMIT 500
        """
    ).fetchall()
    names = [t[0] for t in top]
    placeholders = ",".join("?" for _ in names)

    years = conn.execute(
        f"""SELECT vendor_name, fiscal_year_begin, sum(amount_usd),
                   sum(amount_usd) FILTER (amount_usd > 0)
            FROM read_parquet('{conn_path}') WHERE vendor_name IN ({placeholders})
            GROUP BY 1,2""",
        names,
    ).fetchall()
    depts = conn.execute(
        f"""SELECT vendor_name, business_unit, any_value(department_name), sum(amount_usd)
            FROM read_parquet('{conn_path}') WHERE vendor_name IN ({placeholders})
            GROUP BY 1,2""",
        names,
    ).fetchall()
    progs = conn.execute(
        f"""SELECT vendor_name, program_description, sum(amount_usd)
            FROM read_parquet('{conn_path}') WHERE vendor_name IN ({placeholders})
            GROUP BY 1,2""",
        names,
    ).fetchall()
    conn.close()

    profiles: dict[str, dict[str, Any]] = {
        name: {
            "total_usd": float(total),
            "masked": bool(masked),
            "public_sector": bool(pub),
            "years": {},
            "departments": [],
            "programs": [],
        }
        for name, total, masked, pub in top
    }
    for name, fy, usd, gross in years:
        profiles[name]["years"][fy] = float(usd)
        # keep gross alongside net where adjustments are material
        if gross and float(usd) < float(gross) * 0.95:
            profiles[name].setdefault("years_gross", {})[fy] = float(gross)
    for name, bu, dname, usd in depts:
        profiles[name]["departments"].append(
            {
                "org_cd": bu,
                "title": dname,
                "agency_cd": dept_agency.get(bu),
                "usd": float(usd),
            }
        )
    for name, prog, usd in progs:
        profiles[name]["programs"].append({"program": prog, "usd": float(usd)})
    for p in profiles.values():
        p["departments"].sort(key=lambda d: -d["usd"])
        p["programs"] = sorted(p["programs"], key=lambda x: -x["usd"])[:6]

    storage.put_bytes(
        "published/vendor_profiles.json",
        json.dumps(
            envelope(
                cfg,
                as_of=now.strftime("%Y-%m-%dT%H%M%SZ"),
                ingested_at=now.isoformat(),
                data={"vendors": profiles},
            )
        ).encode(),
        "application/json",
    )
    print(f"{cfg.source}: published vendor_profiles.json ({len(profiles)} vendors)")


def _budget_maps(storage: Storage) -> tuple[dict, dict, dict]:
    """org_cd -> enacted all-funds budget / agency_cd / title, from ebudget_detail output.

    Falls back to the committed site copies on fresh environments.
    """
    from ..config import REPO_ROOT

    site_data = REPO_ROOT / "site" / "public" / "data"

    def _read(key: str) -> bytes | None:
        raw = storage.get_bytes(key)
        if raw is None:
            committed = site_data / key.removeprefix("published/")
            raw = committed.read_bytes() if committed.exists() else None
        return raw

    budgets: dict[str, float] = {}
    agency_of: dict[str, str] = {}
    titles: dict[str, str] = {}
    raw = _read("published/budget_waterfall.json")
    agency_cds = [a["org_cd"] for a in json.loads(raw)["data"]["agencies"]] if raw else []
    for cd in agency_cds:
        doc = _read(f"published/agencies/{cd}.json")
        if not doc:
            continue
        for dept in json.loads(doc)["data"]["departments"]:
            budgets[dept["org_cd"]] = dept["total_usd"]
            agency_of[dept["org_cd"]] = cd
            titles[dept["org_cd"]] = dept["title"]
    return budgets, agency_of, titles

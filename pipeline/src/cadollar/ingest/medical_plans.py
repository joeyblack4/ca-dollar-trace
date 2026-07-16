"""Medi-Cal managed care plans: enrollment + certified capitation rates.

Resolves CSV resource URLs through CKAN package metadata each run (the
enrollment file is renamed every month), cleanses both datasets to parquet,
and publishes one plan-level document: every plan with latest-month
enrollment, counties served, plan model, and its current certified
capitation-rate range. The plan->provider hop stays dark and labeled.
"""

from __future__ import annotations

import hashlib
import json
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

ENROLL_SQL = """
CREATE OR REPLACE TABLE enrollment AS
SELECT
    "Enrollment Month"                                   AS month,
    "Plan Type"                                          AS plan_type,
    County                                               AS county,
    trim("Plan Name")                                    AS plan_name,
    TRY_CAST(replace(trim("Count of Enrollees"), ',', '') AS BIGINT) AS enrollees
FROM read_csv(?, header=true, all_varchar=true);
"""

# The seven capitation model files ship five different header variants
# (trailing spaces, "Rate Period" vs "Rating Period", "PACE Organization" vs
# "Health Plan", SCAN with no plan column, Single Plan with no Midpoint).
# Columns are therefore resolved by normalized name per file; a file whose
# required columns can't be mapped is skipped AND disclosed.
CAP_REQUIRED = ("calendar_year", "county", "category")


def _load_cap_file(conn: duckdb.DuckDBPyConnection, path: str, resource_name: str) -> bool:
    described = conn.execute(
        f"DESCRIBE SELECT * FROM read_csv('{path}', header=true, all_varchar=true)"
    ).fetchall()
    cols = {c[0].strip().lower(): c[0] for c in described}

    def find(*cands: str) -> str | None:
        for cand in cands:
            if cand in cols:
                return cols[cand]
        return None

    year = find("calendar year", "calendar")
    county = find("county")
    category = find("category of aid")
    plan = find("health plan", "health plan name", "pace organization")
    lower = find("lower bound")
    mid = find("midpoint")
    upper = find("upper bound")

    if not (year and county and category and (lower or mid or upper)):
        return False

    def num(col: str | None) -> str:
        if col is None:
            return "NULL"
        return f"TRY_CAST(replace(replace(trim(\"{col}\"), ',', ''), '$', '') AS DOUBLE)"

    # SCAN's file has no plan column — the whole file is one plan
    plan_expr = f'trim("{plan}")' if plan else f"'{_plan_from_resource(resource_name)}'"
    conn.execute(
        f"""
        INSERT INTO capitation
        SELECT TRY_CAST("{year}" AS INTEGER), trim("{county}"), {plan_expr},
               trim("{category}"), {num(lower)}, {num(mid)}, {num(upper)}
        FROM read_csv('{path}', header=true, all_varchar=true)
        """
    )
    return True


def _plan_from_resource(resource_name: str) -> str:
    if "SCAN" in resource_name:
        return "SCAN Health Plan"
    return resource_name


def _resolve_csv_resources(pkg_json: bytes) -> list[dict[str, str]]:
    resources = json.loads(pkg_json)["result"]["resources"]
    return [r for r in resources if r.get("format", "").upper() == "CSV"]


def run_medical_plans(storage: Storage, cfg: SourceConfig, settings: Settings) -> str:
    now = datetime.now(UTC)
    as_of = now.strftime("%Y-%m-%dT%H%M%SZ")
    manifest = read_manifest(storage, cfg.source)

    enroll_pkg = fetch_bytes(cfg.endpoints["enrollment_pkg"])
    cap_pkg = fetch_bytes(cfg.endpoints["capitation_pkg"])

    enroll_res = _resolve_csv_resources(enroll_pkg)
    if len(enroll_res) != 1:
        raise QualityGateError(
            f"{cfg.source}: expected 1 enrollment CSV, found {len(enroll_res)}"
        )
    cap_res = _resolve_csv_resources(cap_pkg)
    if not cap_res:
        raise QualityGateError(f"{cfg.source}: no capitation CSV resources found")

    enroll_csv = fetch_bytes(enroll_res[0]["url"])
    cap_csvs = {r["name"]: fetch_bytes(r["url"]) for r in sorted(cap_res, key=lambda r: r["name"])}

    content_hash = hashlib.sha256(
        enroll_csv + b"".join(cap_csvs.values())
    ).hexdigest()
    if manifest.get("content_hash") == content_hash:
        manifest["checked_at"] = now.isoformat()
        write_manifest(storage, cfg.source, manifest)
        print(f"{cfg.source}: unchanged upstream, no-op")
        return manifest["published_key"]

    storage.put_bytes(
        f"raw/{cfg.source}/{cfg.dataset}/{as_of}/enrollment.csv", enroll_csv, "text/csv"
    )
    for name, body in cap_csvs.items():
        safe = name.replace("/", "_")[:60]
        storage.put_bytes(
            f"raw/{cfg.source}/{cfg.dataset}/{as_of}/cap_{safe}.csv", body, "text/csv"
        )

    doc, row_count = build_plans_doc(enroll_csv, cap_csvs, storage)
    if row_count < cfg.min_rows:
        raise QualityGateError(
            f"{cfg.source}: enrollment panel has {row_count} rows < {cfg.min_rows}"
        )

    key = "published/medical_plans.json"
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
            "row_count": row_count,
            "as_of": as_of,
            "ingested_at": now.isoformat(),
            "checked_at": now.isoformat(),
            "published_key": key,
        },
    )
    print(f"{cfg.source}: published {key}")
    return key


def build_plans_doc(
    enroll_csv: bytes, cap_csvs: dict[str, bytes], storage: Storage
) -> tuple[dict[str, Any], int]:
    with tempfile.TemporaryDirectory() as td:
        conn = duckdb.connect(":memory:")
        ep = Path(td) / "enroll.csv"
        ep.write_bytes(enroll_csv)
        conn.execute(ENROLL_SQL, [str(ep)])

        conn.execute(
            """CREATE TABLE capitation (calendar_year INTEGER, county VARCHAR,
               plan_name VARCHAR, category_of_aid VARCHAR,
               lower_pmpm DOUBLE, midpoint_pmpm DOUBLE, upper_pmpm DOUBLE)"""
        )
        cap_loaded, cap_skipped = 0, []
        for i, (name, body) in enumerate(cap_csvs.items()):
            p = Path(td) / f"cap{i}.csv"
            p.write_bytes(body)
            try:
                ok = _load_cap_file(conn, str(p), name)
            except duckdb.Error:
                ok = False
            if ok:
                cap_loaded += 1
            else:
                # fail-honest: a file whose schema can't be mapped is skipped
                # AND disclosed, never silently absorbed as zero rates
                cap_skipped.append(name)

        row = conn.execute("SELECT count(*), max(month) FROM enrollment").fetchone()
        assert row is not None
        row_count, latest_month = row

        plans = _rows(conn, f"""
            SELECT plan_name,
                   any_value(plan_type)      AS plan_type,
                   sum(enrollees)            AS enrollees,
                   count(DISTINCT county)    AS county_count,
                   count(*) FILTER (enrollees IS NULL) AS suppressed_county_rows
            FROM enrollment WHERE month = '{latest_month}'
            GROUP BY 1 ORDER BY 3 DESC NULLS LAST""")

        cap_latest = _rows(conn, """
            WITH latest AS (
                SELECT plan_name, max(calendar_year) AS yr FROM capitation
                WHERE calendar_year IS NOT NULL GROUP BY 1
            )
            SELECT c.plan_name,
                   l.yr                                          AS rate_year,
                   min(coalesce(c.lower_pmpm, c.midpoint_pmpm))  AS min_pmpm,
                   max(coalesce(c.upper_pmpm, c.midpoint_pmpm))  AS max_pmpm,
                   count(*)                                      AS rate_cells
            FROM capitation c JOIN latest l ON c.plan_name = l.plan_name AND c.calendar_year = l.yr
            WHERE coalesce(c.lower_pmpm, c.midpoint_pmpm, c.upper_pmpm) IS NOT NULL
            GROUP BY 1, 2""")
        conn.close()

    # Deterministic name-resolution waterfall (the two datasets never agree on
    # plan names): normalize -> curated alias -> prefix containment. Every
    # match records its method; the measured match rate is published.
    cap_norm: dict[str, dict[str, Any]] = {}
    for c in cap_latest:
        cap_norm.setdefault(_norm_plan(c["plan_name"]), c)

    matched = 0
    enrollees_total = sum(p["enrollees"] or 0 for p in plans)
    enrollees_matched = 0
    for p in plans:
        n = _norm_plan(p["plan_name"].split("/")[0])
        cap, method = None, None
        if n in cap_norm:
            cap, method = cap_norm[n], "exact"
        elif n in PLAN_ALIASES and _norm_plan(PLAN_ALIASES[n]) in cap_norm:
            cap, method = cap_norm[_norm_plan(PLAN_ALIASES[n])], "alias"
        else:
            for cn, c in cap_norm.items():
                if len(cn) >= 8 and (n.startswith(cn) or cn.startswith(n)):
                    cap, method = c, "prefix"
                    break
        p["capitation"] = cap and {
            "rate_year": cap["rate_year"],
            "pmpm_range": [cap["min_pmpm"], cap["max_pmpm"]],
            "rate_cells": cap["rate_cells"],
            "name_match": method,
        }
        if cap:
            matched += 1
            enrollees_matched += p["enrollees"] or 0

    doc = {
        "latest_month": latest_month,
        "total_enrollees": enrollees_total,
        "plan_count": len(plans),
        "plans": plans,
        # honesty metrics: name-join coverage between the two datasets
        # (count AND enrollee-weighted), and files we could not parse
        "plans_with_capitation_match": matched,
        "enrollee_weighted_match_pct": (
            round(100 * enrollees_matched / enrollees_total, 1) if enrollees_total else None
        ),
        "capitation_files_loaded": cap_loaded,
        "capitation_files_skipped": cap_skipped,
    }
    return doc, int(row_count)


def _norm_plan(name: str) -> str:
    """Aggressive normalization for plan-name joining."""
    n = name.upper().strip()
    for ch in (".", ",", "'", "’", "(", ")", "-"):
        n = n.replace(ch, "")
    n = " ".join(n.split())
    replacements = [
        (" HP", " HEALTH PLAN"),
        (" COMM ", " COMMUNITY "),
        ("CENTRAL CA ALLIANCE", "CENTRAL CALIFORNIA ALLIANCE"),
        ("CALIF ", "CALIFORNIA "),
    ]
    for a, b in replacements:
        if n.endswith(a.rstrip()):
            n = n[: -len(a.rstrip())] + b.rstrip()
        n = n.replace(a, b)
    return n


# Curated corporate-family aliases: the enrollment report names the Medi-Cal
# contracting subsidiary; the rate certifications name the parent/rate entity.
# Kept small, visible, and editorial — every entry is a researched equivalence.
PLAN_ALIASES: dict[str, str] = {
    _norm_plan(k): v
    for k, v in {
        "Health Net Community Solutions": "Health Net of California",
        "Health Net Comm Solutions SAC": "Health Net of California",
        "Health Net Comm Solutions LA": "Health Net of California",
        "Anthem Blue Cross Partnership Plan": "Anthem Blue Cross",
        "Blue Shield of California Promise": "Blue Shield Promise Health Plan of California",
        "Molina Healthcare of California": "Molina Healthcare",
        "California Health & Wellness Plan": "California Health and Wellness",
        "Aetna Better Health of California": "Aetna Better Health",
        "United Health Care Community Plan": "United Healthcare",
        "Kaiser NorCal": "Kaiser Foundation Health Plan",
        "Kaiser SoCal": "Kaiser Foundation Health Plan",
        "Community Health Plan of Imperial Valley": "Community Health Plan Imperial Valley",
    }.items()
}


def _rows(conn: duckdb.DuckDBPyConnection, sql: str) -> list[dict[str, Any]]:
    cur = conn.execute(sql)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]

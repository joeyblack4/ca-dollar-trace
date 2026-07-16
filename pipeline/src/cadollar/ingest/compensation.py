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
import re
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
    _attach_state_org_cds(doc, storage)
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


# Reduce a department name to its core token set for matching across the two
# naming conventions: ebudget writes "State Department of Health Care Services",
# GCC inverts to "Health Care Services, Department of". Both collapse to the
# same {HEALTH, CARE, SERVICES} once the boilerplate is stripped.
_STRIP = re.compile(
    r"\b(STATE|CALIFORNIA|CALIF|DEPARTMENT|DEPT|OF|THE|OFFICE|BOARD|COMMISSION"
    r"|CONTRIBUTIONS|TO|AND|&|FOR|A)\b"
)


def _core(name: str) -> frozenset[str]:
    n = _norm(name).replace(",", " ").replace("(", " ").replace(")", " ")
    n = _STRIP.sub(" ", n)
    return frozenset(t for t in n.split() if len(t) > 2)


def _attach_state_org_cds(doc: dict[str, Any], storage: Storage) -> None:
    """Match state-department payroll to ebudget org_cd by core-token overlap,
    and publish state_by_org_cd for the department drill. Match rate published;
    a token set that maps to two departments is left unmatched (ambiguous),
    never guessed."""
    from ..config import REPO_ROOT

    site = REPO_ROOT / "site" / "public" / "data"

    def read(rel: str) -> dict | None:
        raw = storage.get_bytes(f"published/{rel}")
        if raw is None:
            p = site / rel
            raw = p.read_bytes() if p.exists() else None
        return json.loads(raw) if raw else None

    wf = read("budget_waterfall.json")
    if not wf:
        doc["state_by_org_cd"] = {}
        return

    # org_cd -> (title, core tokens, budget) from the department rosters
    dept_core: dict[str, tuple[str, frozenset[str], float]] = {}
    for a in wf["data"]["agencies"]:
        ag = read(f"agencies/{a['org_cd']}.json")
        if not ag:
            continue
        for d in ag["data"]["departments"]:
            dept_core[d["org_cd"]] = (d["title"], _core(d["title"]), d.get("total_usd") or 0)

    # index by token set; when several departments share tokens, the payroll
    # belongs to the largest by budget (a $10B agency, not a tiny commission)
    tokens_to_cds: dict[frozenset[str], list[str]] = {}
    for cd, (_, toks, _) in dept_core.items():
        if toks:
            tokens_to_cds.setdefault(toks, []).append(cd)

    def _pick(cands: list[str]) -> str | None:
        if not cands:
            return None
        return max(cands, key=lambda c: dept_core[c][2])

    state_emps = doc["levels"]["state"]["top_employers"]  # the 40 worth drilling
    matched: dict[str, dict[str, Any]] = {}
    for e in state_emps:
        toks = _core(e["employer"])
        cd = _pick(tokens_to_cds.get(toks, []))
        if cd is None:
            # fall back to subset/superset overlap, again largest-budget wins
            cands = [
                c for c, (_, dt, _) in dept_core.items()
                if toks and dt and (toks <= dt or dt <= toks)
            ]
            cd = _pick(cands)
        if cd:
            matched[cd] = {
                "employer": e["employer"],
                "positions": e["positions"],
                "wages_usd": e["wages_usd"],
                "benefits_usd": e["benefits_usd"],
            }
    doc["state_by_org_cd"] = matched
    doc["state_departments_matched"] = len(matched)
    doc["state_departments_considered"] = len(state_emps)


def _rows(conn: duckdb.DuckDBPyConnection, sql: str, path: str) -> list[dict[str, Any]]:
    cur = conn.execute(sql, [path])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]

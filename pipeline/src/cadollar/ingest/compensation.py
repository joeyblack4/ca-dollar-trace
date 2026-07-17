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

import csv
import hashlib
import io
import json
import re
import zipfile
from datetime import UTC, datetime
from statistics import median
from typing import Any

from ..config import Settings
from ..publish.envelope import envelope
from ..sources import SourceConfig
from ..storage import Storage, read_manifest, write_manifest
from .csv_download import QualityGateError

# Parsing is plain Python csv, streamed from the zip: the GCC exports are
# cp1252-encoded (accented bytes in Position/Department columns) with a UTF-8
# BOM header — a mix DuckDB's CSV reader rejects under every encoding flag.


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

    fb_bytes: bytes | None = None
    fb_year = int(cfg.extra.get("k12_fallback_year", 0))
    if fb_name := cfg.extra.get("k12_fallback_file"):
        fb_path = captured / fb_name
        if not fb_path.exists():
            raise QualityGateError(f"{cfg.source}: captured file missing: {fb_name}")
        fb_bytes = fb_path.read_bytes()

    content_hash = hashlib.sha256(
        b"".join(raw[k] for k in sorted(raw)) + (fb_bytes or b"")
    ).hexdigest()
    if manifest.get("content_hash") == content_hash:
        manifest["checked_at"] = now.isoformat()
        write_manifest(storage, cfg.source, manifest)
        print(f"{cfg.source}: snapshot unchanged, no-op")
        return manifest["published_key"]

    doc, k12_doc, total_positions = _build(raw, year, fb_bytes, fb_year)
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
    # the K-12 salary drill ships separately: per-district totals + job-title
    # pay bands is district-page data, too big to ride along with every
    # coverage-meter fetch of compensation.json
    if k12_doc:
        storage.put_bytes(
            "published/k12_compensation.json",
            json.dumps(
                envelope(cfg, as_of=as_of, ingested_at=now.isoformat(), data=k12_doc),
                indent=2,
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


def _decode(data: bytes) -> str:
    """GCC files are usually cp1252; some are clean UTF-8 (with or without BOM).
    Try strict UTF-8 first so genuine multibyte text isn't mojibaked, then fall
    back to cp1252 (which maps nearly every byte)."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
        if text.startswith("ï»¿"):  # a UTF-8 BOM read as cp1252
            text = text[3:]
    return text.lstrip("﻿")


def _aggregate(
    text: str, want_titles: bool
) -> tuple[list[dict[str, Any]], dict[str, dict[str, list[tuple[float, float]]]], int]:
    """One pass over a GCC CSV: per-employer totals, and (for the K-12 salary
    drill) per-employer x job-title pay lists."""
    employers: dict[str, dict[str, Any]] = {}
    pay: dict[str, dict[str, list[tuple[float, float]]]] = {}
    unparsed = 0
    reader = csv.reader(io.StringIO(text))
    hdr = next(reader)
    emp_i, pos_i = hdr.index("EmployerName"), hdr.index("Position")
    wage_i = hdr.index("TotalWages")
    ben_i = hdr.index("TotalRetirementAndHealthContribution")
    for row in reader:
        if len(row) != len(hdr):
            unparsed += 1
            continue
        emp = row[emp_i]
        e = employers.get(emp)
        if e is None:
            e = employers[emp] = {
                "employer": emp, "positions": 0, "wages_usd": 0.0,
                "benefits_usd": 0.0, "unparsed": 0,
            }
        e["positions"] += 1
        try:
            w = float(row[wage_i])
            e["wages_usd"] += w
        except ValueError:
            if row[wage_i]:
                e["unparsed"] += 1
            w = None
        try:
            b = float(row[ben_i])
            e["benefits_usd"] += b
        except ValueError:
            b = 0.0
        if want_titles and w is not None and (title := row[pos_i].strip()):
            pay.setdefault(emp, {}).setdefault(title, []).append((w, b))
    rows = sorted(employers.values(), key=lambda r: -r["positions"])
    for r in rows:
        r["unparsed"] += 0  # keep key present even when clean
    if unparsed:
        rows_total = sum(r["positions"] for r in rows)
        print(f"  note: {unparsed} malformed row(s) skipped of {rows_total + unparsed}")
    return rows, pay, unparsed


def _build(
    raw: dict[str, bytes], year: int, k12_fb: bytes | None = None, fb_year: int = 0
) -> tuple[dict[str, Any], dict[str, Any] | None, int]:
    levels: dict[str, dict[str, Any]] = {}
    total_positions = 0
    all_employers: list[dict[str, Any]] = []
    k12_doc: dict[str, Any] | None = None

    for level, body in raw.items():
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            text = _decode(z.read(z.namelist()[0]))
        rows, pay, dropped = _aggregate(text, want_titles=level == "k12")
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
            "unparsed": sum(r["unparsed"] for r in rows) + dropped,
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
        if level == "k12":
            k12_doc = _build_k12(pay, rows, year)
            if k12_fb:
                with zipfile.ZipFile(io.BytesIO(k12_fb)) as z:
                    fb_text = _decode(z.read(z.namelist()[0]))
                fb_rows, fb_pay, _ = _aggregate(fb_text, want_titles=True)
                _merge_k12_fallback(k12_doc, fb_pay, fb_rows, fb_year)

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
    return doc, k12_doc, total_positions


def _build_k12(
    pay: dict[str, dict[str, list[tuple[float, float]]]],
    employer_rows: list[dict[str, Any]],
    year: int,
) -> dict[str, Any]:
    """Per-district payroll with job-title pay bands — the salary drill for the
    K-12 level. Districts are keyed by normalized name so the SACS district list
    can join without re-implementing normalization; a district that doesn't
    match simply shows no payroll panel (absence stays absent)."""

    districts: dict[str, dict[str, Any]] = {}
    statewide: dict[str, list[tuple[float, float]]] = {}
    for e in employer_rows:
        for t, rows in pay.get(e["employer"], {}).items():
            statewide.setdefault(t, []).extend(rows)
        districts[_norm(e["employer"])] = _district_entry(
            e, pay.get(e["employer"], {}), year
        )

    top_statewide = sorted(statewide.items(), key=lambda kv: -len(kv[1]))[:25]
    return {
        "year": year,
        "district_count": len(districts),
        "positions": sum(d["positions"] for d in districts.values()),
        "wages_usd": sum(d["wages_usd"] for d in districts.values()),
        "benefits_usd": sum(d["benefits_usd"] for d in districts.values()),
        "statewide_titles": [
            {k: v for k, v in _band(t, rows).items() if k != "median_benefits_usd"}
            for t, rows in top_statewide
        ],
        "districts": districts,
    }


def _band(title: str, rows: list[tuple[float, float]]) -> dict[str, Any]:
    wages = sorted(w for w, _ in rows)
    return {
        "title": title,
        "positions": len(rows),
        "median_pay_usd": round(median(wages)),
        "max_pay_usd": round(wages[-1]),
        "median_benefits_usd": round(median(sorted(b for _, b in rows))),
    }


def _district_entry(
    e: dict[str, Any], emp_pay: dict[str, list[tuple[float, float]]], year: int
) -> dict[str, Any]:
    titles = [_band(t, rows) for t, rows in emp_pay.items()]
    # what people come for: the common jobs (top by headcount) AND the
    # leadership pay (top by median, catches the one-seat Superintendent)
    by_count = sorted(titles, key=lambda t: -t["positions"])[:10]
    by_pay = sorted(titles, key=lambda t: -t["median_pay_usd"])[:6]
    seen: set[str] = set()
    picked = [
        t for t in by_count + by_pay
        if not (t["title"] in seen or seen.add(t["title"]))  # type: ignore[func-returns-value]
    ]
    return {
        "name": e["employer"],
        "year": year,
        "positions": e["positions"],
        "wages_usd": e["wages_usd"] or 0,
        "benefits_usd": e["benefits_usd"] or 0,
        "title_count": len(titles),
        "titles": sorted(picked, key=lambda t: -t["positions"]),
    }


def _merge_k12_fallback(
    k12_doc: dict[str, Any],
    fb_pay: dict[str, dict[str, list[tuple[float, float]]]],
    fb_rows: list[dict[str, Any]],
    fb_year: int,
) -> None:
    """A district that skipped the latest filing keeps its LAST filed year,
    labeled with that year (LAUSD filed 2023 but not 2024). Statewide totals
    and title medians stay latest-year-only — mixing years would double-count
    nothing but would sum unlike periods."""
    recovered = 0
    for e in fb_rows:
        key = _norm(e["employer"])
        if key in k12_doc["districts"]:
            continue
        k12_doc["districts"][key] = _district_entry(e, fb_pay.get(e["employer"], {}), fb_year)
        recovered += 1
    # district_count / positions / wages stay latest-year-only; the recovered
    # districts are countable separately and labeled per-entry by their year
    k12_doc["fallback_year"] = fb_year
    k12_doc["fallback_district_count"] = recovered


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

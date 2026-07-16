"""ebudget department detail: programs + funds for every department.

Membership comes from the summary's own grouping — statistics/{agency_cd}
returns the departments each agency group counts, with per-department fund
totals. Per department we then fetch program lines (orgProgram) and per-fund
detail (rwaCntl/support). Units arrive in $ thousands, normalized to dollars.

Fail-honest rules:
  - department program lines are integrity-checked against the department's
    own statistics total; mismatches are flagged and shown, never dropped
  - a department with no program endpoint keeps its statistics dollars and an
    explicit "no program detail published" flag
  - agency roll-ups must reconcile with the already-published summary
    (budget_waterfall.json) — drift > 0.5% aborts the publish
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

import httpx

from ..config import Settings
from ..publish.envelope import envelope
from ..sources import SourceConfig
from ..storage import Storage, read_manifest, write_manifest
from .csv_download import QualityGateError
from .http import fetch_bytes

K = 1_000  # $ thousands -> dollars

FUND_CLASS_LABEL = {
    "G": "General Fund",
    "S": "Special funds",
    "F": "Federal funds",
    "B": "Bond funds",
}


def run_ebudget_detail(storage: Storage, cfg: SourceConfig, settings: Settings) -> list[str]:
    now = datetime.now(UTC)
    as_of = now.strftime("%Y-%m-%dT%H%M%SZ")
    manifest = read_manifest(storage, cfg.source)

    summary = _load_summary(storage)
    agency_summaries = summary["agencies"]

    per_agency: dict[str, list[dict[str, Any]]] = {}
    dept_count = 0
    for agency in agency_summaries:
        cd = agency["org_cd"]
        members = json.loads(fetch_bytes(cfg.endpoints["agency_stats"].format(agency_cd=cd)))
        detailed = []
        for m in members:
            org_cd = m["orgCd"]
            detailed.append(
                {
                    "stats": m,
                    "programs": _fetch_json_or_none(
                        cfg.endpoints["org_program"].format(org_cd=org_cd)
                    ),
                    "funds": _fetch_json_or_none(
                        cfg.endpoints["fund_support"].format(org_cd=org_cd)
                    ),
                    "cap_outlay": _fetch_json_or_none(
                        cfg.endpoints["cap_outlay"].format(org_cd=org_cd)
                    ),
                }
            )
            dept_count += 1
        per_agency[cd] = detailed

    if dept_count < cfg.min_rows:
        raise QualityGateError(f"{cfg.source}: only {dept_count} departments < {cfg.min_rows}")

    blob = json.dumps(per_agency, sort_keys=True).encode()
    content_hash = hashlib.sha256(blob).hexdigest()
    if manifest.get("content_hash") == content_hash:
        manifest["checked_at"] = now.isoformat()
        write_manifest(storage, cfg.source, manifest)
        print(f"{cfg.source}: unchanged upstream, no-op")
        return manifest.get("published_keys", [])

    storage.put_bytes(
        f"raw/{cfg.source}/{cfg.dataset}/{as_of}/departments.json", blob, "application/json"
    )

    agencies = build_agency_details(per_agency, agency_summaries)

    published_keys: list[str] = []
    for agency_cd, agency_doc in sorted(agencies.items()):
        key = f"published/agencies/{agency_cd}.json"
        storage.put_bytes(
            key,
            json.dumps(
                envelope(cfg, as_of=as_of, ingested_at=now.isoformat(), data=agency_doc),
                indent=2,
            ).encode(),
            "application/json",
        )
        published_keys.append(key)

    write_manifest(
        storage,
        cfg.source,
        {
            "content_hash": content_hash,
            "row_count": dept_count,
            "as_of": as_of,
            "ingested_at": now.isoformat(),
            "checked_at": now.isoformat(),
            "published_keys": published_keys,
        },
    )
    print(f"{cfg.source}: {dept_count} departments -> {len(published_keys)} agency files")
    return published_keys


def _load_summary(storage: Storage) -> dict[str, Any]:
    raw = storage.get_bytes("published/budget_waterfall.json")
    if raw is None:
        # fresh environment (e.g. CI runner) where the enacted source no-op'd:
        # fall back to the committed copy the site serves
        from ..config import REPO_ROOT

        committed = REPO_ROOT / "site" / "public" / "data" / "budget_waterfall.json"
        if committed.exists():
            raw = committed.read_bytes()
        else:
            raise QualityGateError(
                "ebudget_detail requires budget_waterfall.json; run ebudget_enacted first"
            )
    return json.loads(raw)["data"]


def _fetch_json_or_none(url: str) -> Any | None:
    try:
        return json.loads(fetch_bytes(url))
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return None
        raise


def build_agency_details(
    per_agency: dict[str, list[dict[str, Any]]],
    agency_summaries: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    summaries_by_cd = {a["org_cd"]: a for a in agency_summaries}
    agencies: dict[str, dict[str, Any]] = {}

    for agency_cd, members in per_agency.items():
        ref = summaries_by_cd[agency_cd]
        departments = []
        rollup = 0

        for m in members:
            stats = m["stats"]
            stat_total = (stats.get("allBudgetYearDols") or 0) * K
            rollup += stat_total

            lines = []
            integrity: dict[str, Any] = {}
            if m["programs"]:
                lines = [
                    {
                        "program_code": ln.get("programCode"),
                        "title": (ln.get("programTitl") or "").strip(),
                        "usd": (ln.get("byDols") or 0) * K,
                        "positions": ln.get("byPersYrs"),
                    }
                    for ln in m["programs"].get("lines", [])
                ]
                # capital outlay is published as a separate schedule; append it
                # as its own line so program sums can honestly match totals
                cap = sum(
                    (f.get("byTotDols") or 0) * K
                    for f in (m.get("cap_outlay") or [])
                    if isinstance(f, dict)
                )
                if cap:
                    lines.append(
                        {
                            "program_code": None,
                            "title": "Capital outlay projects (separate ebudget schedule)",
                            "usd": cap,
                            "positions": None,
                        }
                    )
                lines_sum = sum(ln["usd"] for ln in lines)
                integrity = {
                    "program_lines_sum_usd": lines_sum,
                    "matches_department_total": abs(lines_sum - stat_total)
                    <= max(1_000_000, stat_total * 0.001),
                }
            else:
                integrity = {"no_program_detail_published": True}

            funds_by_class: dict[str, int] = {}
            for f in m["funds"] if isinstance(m["funds"], list) else []:
                label = FUND_CLASS_LABEL.get(f.get("fundClassCd"), "Other funds")
                funds_by_class[label] = (
                    funds_by_class.get(label, 0) + (f.get("byTotDols") or 0) * K
                )

            departments.append(
                {
                    "org_cd": stats["orgCd"],
                    "title": stats.get("legalTitl") or stats.get("webIndexName") or "",
                    "total_usd": stat_total,
                    "general_fund_usd": (stats.get("generalFundTotal") or 0) * K,
                    "positions": stats.get("budgetYearPers"),
                    "programs": sorted(lines, key=lambda x: -x["usd"]),
                    "funds_by_class": dict(
                        sorted(funds_by_class.items(), key=lambda kv: -kv[1])
                    ),
                    "integrity": integrity,
                }
            )

        # --- hard gate: members must reconcile with the published summary ---
        ref_total = ref["all_funds_usd"]
        drift = abs(rollup - ref_total) / ref_total if ref_total else 0
        if drift > 0.005:
            raise QualityGateError(
                f"ebudget_detail: agency {agency_cd} members sum {rollup} but summary says "
                f"{ref_total} ({drift:.1%} drift); refusing to publish"
            )

        departments.sort(key=lambda d: -d["total_usd"])
        agencies[agency_cd] = {
            "agency_cd": agency_cd,
            "title": ref["title"],
            "total_usd": rollup,
            "summary_cross_check": {
                "summary_all_funds_usd": ref_total,
                "drift_pct": round(drift * 100, 3),
            },
            "departments": departments,
        }

    return agencies

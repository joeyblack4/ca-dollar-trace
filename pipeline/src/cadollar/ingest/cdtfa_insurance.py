"""CDTFA Insurance Tax: gross-premiums tax assessed, by insurer type.

Publishes published/revenue/insurance.json. Insurer type is the finest public
cut for tax paid — named-insurer tax is not public anywhere (CDI publishes
premiums by company, not tax).

Fail-honest rules:
  - only leaf insurer types are published; they must reconcile with the
    file's own "Totals" row, and Totals + net adjustments with "Grand
    Totals", within 0.5% each — otherwise the flat export's shape changed
    and we refuse to publish
  - adjustments (refunds, deficiency assessments) are one visible line,
    never netted silently into the types
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from ..config import Settings
from ..publish.envelope import envelope
from ..sources import SourceConfig
from ..storage import Storage, read_manifest, write_manifest
from .cdtfa_sales import CDTFA_USER_AGENT
from .csv_download import QualityGateError
from .ebudget_detail import _load_summary
from .http import fetch_bytes

WATERFALL_REVENUE_NAME = "Insurance Tax"

LEAF_TYPES = {"Fire and Casualty", "Life", "Ocean Marine", "Title"}
NET_ADJUSTMENTS = "Adjustments Net adjustments"


def run_cdtfa_insurance(storage: Storage, cfg: SourceConfig, settings: Settings) -> list[str]:
    now = datetime.now(UTC)
    as_of = now.strftime("%Y-%m-%dT%H%M%SZ")
    manifest = read_manifest(storage, cfg.source)

    rows = json.loads(fetch_bytes(cfg.endpoints["assessed"], user_agent=CDTFA_USER_AGENT)).get(
        "value", []
    )
    content_hash = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
    if manifest.get("content_hash") == content_hash:
        manifest["checked_at"] = now.isoformat()
        write_manifest(storage, cfg.source, manifest)
        print(f"{cfg.source}: unchanged upstream, no-op")
        return manifest.get("published_keys", [])

    storage.put_bytes(
        f"raw/{cfg.source}/{cfg.dataset}/{as_of}/assessed.json",
        json.dumps(rows).encode(),
        "application/json",
    )

    doc = build_insurance_doc(rows, _load_summary(storage), min_rows=cfg.min_rows)

    key = "published/revenue/insurance.json"
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
            "row_count": len(doc["types"]),
            "as_of": as_of,
            "ingested_at": now.isoformat(),
            "checked_at": now.isoformat(),
            "published_keys": [key],
        },
    )
    print(f"{cfg.source}: assessment year {doc['assessment_year']} — {len(doc['types'])} types")
    return [key]


def build_insurance_doc(
    rows: list[dict[str, Any]], waterfall: dict[str, Any], min_rows: int = 4
) -> dict[str, Any]:
    year = max(r["AssessmentYear"] for r in rows)
    latest = {r["TypeOfInsurer"].strip(): r for r in rows if r["AssessmentYear"] == year}

    types = []
    for name in sorted(LEAF_TYPES):
        r = latest.get(name)
        if r is None:
            raise QualityGateError(f"cdtfa_insurance: insurer type {name!r} missing for {year}")
        types.append(
            {
                "type": name,
                "businesses": r.get("NumberOfBusinesses"),
                "assessed_usd": r.get("AssessedAmount") or 0,
            }
        )
    if len(types) < min_rows:
        raise QualityGateError(f"cdtfa_insurance: only {len(types)} insurer types")
    types.sort(key=lambda t: -t["assessed_usd"])

    leaf_sum = sum(t["assessed_usd"] for t in types)
    totals = (latest.get("Totals") or {}).get("AssessedAmount") or 0
    grand = (latest.get("Grand Totals") or {}).get("AssessedAmount") or 0
    net_adj = (latest.get(NET_ADJUSTMENTS) or {}).get("AssessedAmount") or 0
    if not totals or abs(leaf_sum - totals) / totals > 0.005:
        raise QualityGateError(
            f"cdtfa_insurance: leaf types sum {leaf_sum} vs Totals {totals} — shape changed"
        )
    if grand and abs((totals + net_adj) - grand) / grand > 0.005:
        raise QualityGateError(
            f"cdtfa_insurance: Totals {totals} + adjustments {net_adj} vs Grand {grand}"
        )
    for t in types:
        t["share_pct"] = round(t["assessed_usd"] / totals * 100, 2)

    rev = next(
        (r for r in waterfall["general_fund"]["revenue"] if r["name"] == WATERFALL_REVENUE_NAME),
        None,
    )
    if rev is None:
        raise QualityGateError(
            f"cdtfa_insurance: waterfall has no revenue item {WATERFALL_REVENUE_NAME!r}"
        )
    ratio = grand / rev["usd"] if rev["usd"] and grand else 0
    if not 0.4 <= ratio <= 1.6:
        raise QualityGateError(
            f"cdtfa_insurance: assessed {grand} vs waterfall {rev['usd']} — "
            f"ratio {ratio:.2f} outside sanity band"
        )

    business_year = (latest.get("Totals") or {}).get("BusinessYear")
    return {
        "assessment_year": year,
        "business_year": business_year,
        "budget_reference": {
            "budget_year": waterfall.get("budget_year"),
            "waterfall_usd": rev["usd"],
            "stats_total_usd": grand,
            "note": (
                "The budget waterfall shows the Department of Finance's enacted estimate for "
                f"{waterfall.get('budget_year')}. CDTFA assessed ${grand / 1e9:.2f}B on "
                f"premiums written in {business_year} — close measures, different timing "
                "and scope, shown side by side."
            ),
        },
        "types": types,
        "net_adjustments_usd": net_adj,
        "reconciliation": {
            "leaf_sum_usd": leaf_sum,
            "totals_usd": totals,
            "grand_totals_usd": grand,
        },
    }

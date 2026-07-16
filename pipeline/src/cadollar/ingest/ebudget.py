"""ebudget.ca.gov connector: enacted-budget sankey + per-agency statistics.

Small structured JSON (KBs), so the flow is: fetch both endpoints -> combined
content hash -> archive raw JSON -> validate cross-totals (fail-honest) ->
publish the waterfall document. Units are normalized to DOLLARS here
(sankey arrives in $ millions, statistics in $ thousands).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

import yaml

from ..config import Settings
from ..publish.envelope import envelope
from ..sources import SourceConfig
from ..storage import Storage, read_manifest, write_manifest
from .csv_download import QualityGateError
from .http import fetch_bytes

SANKEY_UNIT = 1_000_000  # $ millions -> dollars
STATS_UNIT = 1_000  # $ thousands -> dollars


def run_ebudget(storage: Storage, cfg: SourceConfig, settings: Settings) -> str:
    now = datetime.now(UTC)
    as_of = now.strftime("%Y-%m-%dT%H%M%SZ")
    manifest = read_manifest(storage, cfg.source)

    raw = {name: fetch_bytes(url) for name, url in sorted(cfg.endpoints.items())}
    content_hash = hashlib.sha256(b"".join(raw.values())).hexdigest()

    if manifest.get("content_hash") == content_hash:
        manifest["checked_at"] = now.isoformat()
        write_manifest(storage, cfg.source, manifest)
        print(f"{cfg.source}: unchanged upstream, no-op")
        return manifest["published_key"]

    for name, body in raw.items():
        storage.put_bytes(
            f"raw/{cfg.source}/{cfg.dataset}/{as_of}/{name}.json", body, "application/json"
        )

    sankey = json.loads(raw["sankey"])
    stats = json.loads(raw["statistics"])
    doc = build_waterfall(sankey, stats, settings)

    key = "published/budget_waterfall.json"
    published = envelope(cfg, as_of=as_of, ingested_at=now.isoformat(), data=doc)
    storage.put_bytes(key, json.dumps(published, indent=2).encode(), "application/json")

    write_manifest(
        storage,
        cfg.source,
        {
            "content_hash": content_hash,
            "row_count": len(stats),
            "as_of": as_of,
            "ingested_at": now.isoformat(),
            "checked_at": now.isoformat(),
            "published_key": key,
        },
    )
    print(f"{cfg.source}: ingested + published {key}")
    return key


def build_waterfall(
    sankey: dict[str, Any], stats: list[dict[str, Any]], settings: Settings
) -> dict[str, Any]:
    nodes = {n["node"]: n["name"] for n in sankey["nodes"]}
    # the center General Fund hub is the blank-named node; anything else is a
    # schema change we must not guess through
    blanks = [i for i, name in nodes.items() if name == ""]
    if len(blanks) != 1:
        raise QualityGateError(
            f"ebudget sankey: expected exactly one blank hub node, found {len(blanks)}"
        )
    gf_id = blanks[0]

    revenue = [
        {"name": nodes[link["source"]], "usd": link["value"] * SANKEY_UNIT}
        for link in sankey["links"]
        if link["target"] == gf_id
    ]
    expenditure = [
        {"name": nodes[link["target"]], "usd": link["value"] * SANKEY_UNIT}
        for link in sankey["links"]
        if link["source"] == gf_id
    ]

    revenue_total = sankey["revenueTotal"] * SANKEY_UNIT
    expenditure_total = sankey["expenditureTotal"] * SANKEY_UNIT

    # --- fail-honest cross-checks: refuse to publish numbers that don't add up
    # (tolerance instead of float equality: fractional-million inputs must not
    # spuriously trip the gate)
    def _off(total: float, parts: float) -> bool:
        return abs(total - parts) > max(1.0, abs(total) * 1e-9)

    if _off(revenue_total, sum(r["usd"] for r in revenue)):
        raise QualityGateError("ebudget sankey: revenue links do not sum to revenueTotal")
    if _off(expenditure_total, sum(e["usd"] for e in expenditure)):
        raise QualityGateError("ebudget sankey: expenditure links do not sum to expenditureTotal")

    grand_totals = {a["stateGrandTotal"] for a in stats}
    if len(grand_totals) != 1:
        raise QualityGateError("ebudget statistics: agencies disagree on stateGrandTotal")
    state_grand_total = grand_totals.pop() * STATS_UNIT
    state_sum = sum(a["stateBudgetYearDols"] for a in stats) * STATS_UNIT
    if abs(state_sum - state_grand_total) / state_grand_total > 0.005:
        raise QualityGateError(
            f"ebudget statistics: agency state funds sum {state_sum} != grand total "
            f"{state_grand_total} (>0.5% off)"
        )

    hidden = [a for a in stats if a.get("displayOnWebFlg") != "Y"]
    agencies = sorted(
        (
            {
                "org_cd": a["orgCd"],
                "title": a["legalTitl"],
                "state_funds_usd": a["stateBudgetYearDols"] * STATS_UNIT,
                "all_funds_usd": a["allBudgetYearDols"] * STATS_UNIT,
                "general_fund_usd": a["generalFundTotal"] * STATS_UNIT,
                "special_fund_usd": a["specialFundTotal"] * STATS_UNIT,
                "bond_fund_usd": a["bondFundTotal"] * STATS_UNIT,
                "positions": a["budgetYearPers"],
            }
            for a in stats
            if a.get("displayOnWebFlg") == "Y"
        ),
        key=lambda a: -a["all_funds_usd"],
    )

    downstream_path = settings.sources_dir / "curated" / "downstream_visibility.yaml"
    with open(downstream_path) as f:
        downstream = yaml.safe_load(f)

    return {
        "budget_year": "2025-26",
        "basis": "enacted",
        "general_fund": {
            "revenue": sorted(revenue, key=lambda r: -r["usd"]),
            "expenditure": sorted(expenditure, key=lambda e: -e["usd"]),
            "revenue_total_usd": revenue_total,
            "expenditure_total_usd": expenditure_total,
            "gap_usd": expenditure_total - revenue_total,
        },
        "agencies": agencies,
        # rows the source itself hides from display but counts in the grand
        # total — disclosed so the published list reconciles to the total
        "agencies_excluded_from_display": {
            "count": len(hidden),
            "state_funds_usd": sum((a.get("stateBudgetYearDols") or 0) for a in hidden)
            * STATS_UNIT,
        },
        "state_grand_total_usd": state_grand_total,
        "downstream_visibility": downstream,
    }

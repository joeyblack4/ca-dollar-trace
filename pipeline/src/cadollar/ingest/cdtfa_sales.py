"""CDTFA Sales & Use Tax: business types, cities, and the fund split.

Publishes published/revenue/sales.json from three OData entity sets:
  Taxable_Sales_by_Type_of_Business — quarterly, mixed-hierarchy NAICS rows
  Taxable_Sales_by_City             — quarterly, with disclosure suppression
  Summary_of_Revenues               — annual actual revenue by tax program/fund

Fail-honest rules:
  - the business-type table mixes hierarchy levels; we publish the mutually
    exclusive partition (13 retail/food group heads + the "All Other Outlets"
    sector rows) and it must reconcile with the file's own "Total All
    Outlets" rows within 0.5% or the publish aborts
  - taxable SALES are the base, not the tax — the doc carries the actual
    fund split (who gets the money) from Summary_of_Revenues alongside
  - suppressed city cells (R&TC §7056) are published as null + counted
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
from .csv_download import QualityGateError
from .ebudget_detail import _load_summary
from .http import fetch_bytes

WATERFALL_REVENUE_NAME = "Sales and Use Tax"

# CDTFA's WAF rejects plain tool user-agents; a compatible-style bot UA passes
CDTFA_USER_AGENT = "Mozilla/5.0 (compatible; ca-dollar-trace/0.1; +https://github.com/ca-dollar-trace)"

# categories whose single row IS the group (no " - Group" suffix, no children)
SINGLE_ROW_CATEGORIES = {
    "Electronics and Appliance Stores",
    "Gasoline Stations",
    "General Merchandise Stores",
    "Nonstore Retailers",
}

TOTAL_ALL_OUTLETS = "Total All Outlets"

# sales-tax fund split in Summary_of_Revenues: program group -> display label
SALES_FUND_GROUPS = {
    "State taxes": "State General Fund",
    "Special district taxes": "Special tax districts (local add-on rates)",
    "City and county taxes": "Cities & counties (Bradley-Burns 1%)",
    "Local Revenue Fund 2011 state sales tax": "Local Revenue Fund 2011 (realignment)",
    "Local revenue fund state sales tax": "Local Revenue Fund (1991 realignment)",
    "Public safety fund sales tax": "Public Safety Fund (Prop 172)",
}


def _fetch_odata(url: str) -> list[dict[str, Any]]:
    """Fetch an OData entity set, following server-side pagination if present."""
    rows: list[dict[str, Any]] = []
    next_url: str | None = url
    while next_url:
        payload = json.loads(fetch_bytes(next_url, user_agent=CDTFA_USER_AGENT))
        rows.extend(payload.get("value", []))
        next_url = payload.get("@odata.nextLink")
    return rows


def _is_partition_row(r: dict[str, Any]) -> bool:
    cat = (r.get("BusinessTypeCategory") or "").strip()
    typ = (r.get("BusinessType") or "").strip()
    if cat == "All Other Outlets":
        return True  # sector-level leaves, incl. "Others"
    if cat.endswith(" - Group"):
        return typ == cat[: -len(" - Group")].strip()
    return cat in SINGLE_ROW_CATEGORIES and typ == cat


def run_cdtfa_sales(storage: Storage, cfg: SourceConfig, settings: Settings) -> list[str]:
    now = datetime.now(UTC)
    as_of = now.strftime("%Y-%m-%dT%H%M%SZ")
    manifest = read_manifest(storage, cfg.source)
    year_min = now.year - 2

    raw = {
        "biz": _fetch_odata(cfg.endpoints["biz"].format(year_min=year_min)),
        "city": _fetch_odata(cfg.endpoints["city"].format(year_min=year_min)),
        "sumrev": _fetch_odata(cfg.endpoints["sumrev"]),
    }

    content_hash = hashlib.sha256(
        json.dumps(raw, sort_keys=True, default=str).encode()
    ).hexdigest()
    if manifest.get("content_hash") == content_hash:
        manifest["checked_at"] = now.isoformat()
        write_manifest(storage, cfg.source, manifest)
        print(f"{cfg.source}: unchanged upstream, no-op")
        return manifest.get("published_keys", [])

    for name, rows in raw.items():
        storage.put_bytes(
            f"raw/{cfg.source}/{cfg.dataset}/{as_of}/{name}.json",
            json.dumps(rows).encode(),
            "application/json",
        )

    doc = build_sales_doc(
        biz=raw["biz"],
        city=raw["city"],
        sumrev=raw["sumrev"],
        waterfall=_load_summary(storage),
        min_rows=cfg.min_rows,
    )

    key = "published/revenue/sales.json"
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
            "row_count": len(doc["business_types"]) + len(doc["cities"]),
            "as_of": as_of,
            "ingested_at": now.isoformat(),
            "checked_at": now.isoformat(),
            "published_keys": [key],
        },
    )
    print(
        f"{cfg.source}: {doc['latest_quarter']} — {len(doc['business_types'])} business "
        f"types, {len(doc['cities'])} cities ({doc['suppressed_city_count']} suppressed)"
    )
    return [key]


def build_sales_doc(
    biz: list[dict[str, Any]],
    city: list[dict[str, Any]],
    sumrev: list[dict[str, Any]],
    waterfall: dict[str, Any],
    min_rows: int = 30,
    min_cities: int = 300,
) -> dict[str, Any]:
    q_order = {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4}
    quarters = sorted(
        {(r["CalendarYear"], r["Quarter"]) for r in biz},
        key=lambda q: (q[0], q_order[q[1]]),
    )
    if len(quarters) < 4:
        raise QualityGateError(f"cdtfa_sales: only {len(quarters)} quarters fetched")
    trailing = quarters[-4:]
    trailing_set = set(trailing)
    latest_quarter = f"{trailing[-1][0]}-{trailing[-1][1]}"

    # ---- business types: trailing-4Q sums over the mutually exclusive partition ----
    types: dict[str, dict[str, Any]] = {}
    total_all_outlets = 0
    for r in biz:
        if (r["CalendarYear"], r["Quarter"]) not in trailing_set:
            continue
        if (r.get("BusinessTypeCategory") or "").strip() == TOTAL_ALL_OUTLETS:
            total_all_outlets += r.get("TaxableTransactionsAmount") or 0
            continue
        if not _is_partition_row(r):
            continue
        label = r["BusinessType"].strip()
        t = types.setdefault(
            label,
            {
                "label": label,
                "naics": str(r.get("NAICS") or ""),
                "taxable_sales_usd": 0,
                "permits": None,
            },
        )
        t["taxable_sales_usd"] += r.get("TaxableTransactionsAmount") or 0
        if (r["CalendarYear"], r["Quarter"]) == trailing[-1]:
            t["permits"] = r.get("NumberOfPermits")

    if len(types) < min_rows:
        raise QualityGateError(f"cdtfa_sales: only {len(types)} business types in partition")
    partition_sum = sum(t["taxable_sales_usd"] for t in types.values())
    if not total_all_outlets:
        raise QualityGateError("cdtfa_sales: no 'Total All Outlets' rows found")
    if abs(partition_sum - total_all_outlets) / total_all_outlets > 0.005:
        raise QualityGateError(
            f"cdtfa_sales: partition sums {partition_sum} vs file total {total_all_outlets} — "
            "the hierarchy rule is stale, refusing to publish"
        )
    business_types = sorted(types.values(), key=lambda t: -t["taxable_sales_usd"])
    for t in business_types:
        t["share_pct"] = round(t["taxable_sales_usd"] / total_all_outlets * 100, 2)

    # ---- cities + counties: trailing-4Q sums, suppression preserved ----
    # the City column mixes real cities with county-total rows ("X COUNTY",
    # uppercase); San Francisco is city-and-county and appears only as a city
    cities: dict[tuple[str, str], dict[str, Any]] = {}
    counties: dict[str, dict[str, Any]] = {}
    for r in city:
        if (r["CalendarYear"], r["Quarter"]) not in trailing_set:
            continue
        name = r["City"].strip()
        county_name = (r.get("County") or "").strip()
        amount = r.get("TotalAllOutletsTaxableTransactions")
        suppressed = bool(r.get("DisclosureFlag")) or amount is None
        if name.upper().endswith(" COUNTY"):
            c = counties.setdefault(
                county_name, {"county": county_name, "taxable_sales_usd": 0, "suppressed": False}
            )
        else:
            c = cities.setdefault(
                (name, county_name),
                {"city": name, "county": county_name, "taxable_sales_usd": 0, "suppressed": False},
            )
        if suppressed:
            c["suppressed"] = True
        else:
            c["taxable_sales_usd"] += amount
    if len(cities) < min_cities:
        raise QualityGateError(f"cdtfa_sales: only {len(cities)} cities fetched")
    if not 50 <= len(counties) <= 58:
        raise QualityGateError(f"cdtfa_sales: {len(counties)} county rows — split rule is stale")
    # San Francisco (city-and-county) may lack a county-total row; use its
    # city row (name casing varies by quarter in the source)
    sf = next((c for (n, _), c in cities.items() if n.upper() == "SAN FRANCISCO"), None)
    if sf and "San Francisco" not in counties:
        counties["San Francisco"] = {
            "county": "San Francisco",
            "taxable_sales_usd": sf["taxable_sales_usd"],
            "suppressed": sf["suppressed"],
        }
    county_rows = sorted(counties.values(), key=lambda c: -c["taxable_sales_usd"])
    # counties must roughly re-add to the statewide total from the biz table
    county_sum = sum(c["taxable_sales_usd"] for c in county_rows)
    if abs(county_sum - total_all_outlets) / total_all_outlets > 0.02:
        raise QualityGateError(
            f"cdtfa_sales: counties sum {county_sum} vs statewide {total_all_outlets} — "
            "geographic rows no longer partition the state"
        )
    city_rows = sorted(cities.values(), key=lambda c: -c["taxable_sales_usd"])
    suppressed_count = sum(1 for c in city_rows if c["suppressed"])
    for c in city_rows:
        if c["suppressed"] and not c["taxable_sales_usd"]:
            c["taxable_sales_usd"] = None  # fully suppressed: null, never zero

    # ---- fund split: latest complete fiscal year in Summary_of_Revenues ----
    sales_rows = [r for r in sumrev if r["TaxProgramGroup"] in SALES_FUND_GROUPS]
    gf_by_fy: dict[int, float] = {}
    for r in sales_rows:
        if r["TaxProgramGroup"] == "State taxes":
            gf_by_fy[r["FiscalYearFrom"]] = (r.get("Revenue") or 0) + gf_by_fy.get(
                r["FiscalYearFrom"], 0
            )
    # newest FY where the GF figure is actually reported (>0), not a placeholder
    complete_fys = [fy for fy, v in gf_by_fy.items() if v > 0]
    if not complete_fys:
        raise QualityGateError("cdtfa_sales: no fiscal year with a General Fund sales figure")
    fund_fy = max(complete_fys)
    fund_split = []
    for r in sales_rows:
        if r["FiscalYearFrom"] != fund_fy:
            continue
        fund_split.append(
            {
                "fund": SALES_FUND_GROUPS[r["TaxProgramGroup"]],
                "revenue_usd": r.get("Revenue") or 0,
            }
        )
    fund_split.sort(key=lambda f: -f["revenue_usd"])
    gf_actual = gf_by_fy[fund_fy]

    # ---- budget reference ----
    rev = next(
        (r for r in waterfall["general_fund"]["revenue"] if r["name"] == WATERFALL_REVENUE_NAME),
        None,
    )
    if rev is None:
        raise QualityGateError(
            f"cdtfa_sales: waterfall has no revenue item {WATERFALL_REVENUE_NAME!r}"
        )
    ratio = gf_actual / rev["usd"] if rev["usd"] else 0
    if not 0.5 <= ratio <= 1.5:
        raise QualityGateError(
            f"cdtfa_sales: FY{fund_fy} GF sales {gf_actual} vs waterfall {rev['usd']} — "
            f"ratio {ratio:.2f} outside sanity band"
        )

    return {
        "latest_quarter": latest_quarter,
        "trailing_quarters": [f"{y}-{q}" for y, q in trailing],
        "budget_reference": {
            "budget_year": waterfall.get("budget_year"),
            "waterfall_usd": rev["usd"],
            "stats_total_usd": int(gf_actual),
            "note": (
                "The budget waterfall shows the Department of Finance's enacted General Fund "
                f"estimate for {waterfall.get('budget_year')}. CDTFA's Summary of Revenues shows "
                f"the General Fund actually received ${gf_actual / 1e9:.1f}B in "
                f"{fund_fy}-{str(fund_fy + 1)[2:]}, the latest complete fiscal year — close "
                "measures, different years, shown side by side."
            ),
        },
        "fund_split_fiscal_year": f"{fund_fy}-{str(fund_fy + 1)[2:]}",
        "fund_split": fund_split,
        "business_types": business_types,
        "business_type_reconciliation": {
            "partition_sum_usd": partition_sum,
            "total_all_outlets_usd": total_all_outlets,
        },
        "counties": county_rows,
        "county_reconciliation": {
            "counties_sum_usd": county_sum,
            "statewide_total_usd": total_all_outlets,
        },
        "cities": city_rows,
        "suppressed_city_count": suppressed_count,
        "base_note": (
            "Business-type and city figures are TAXABLE SALES — the base the tax is applied "
            "to, not tax collected. The General Fund receives its slice of the statewide rate; "
            "the fund split above shows who actually gets the money."
        ),
    }

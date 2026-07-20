"""FTB Personal Income Tax statistics: who pays PIT, as far as the law allows.

Publishes two things from four FTB CSVs (data.ca.gov):
  published/revenue/pit.json           — statewide brackets (B-4A, condensed to
                                         presentation bands), high-income tiers
                                         (B-4A top classes), counties (B-7)
  published/revenue/pit_zip/{slug}.json — per-county ZIP totals (ZIP table)

Fail-honest rules:
  - B-4A band sums must reconcile exactly-ish with B-3's independent totals;
    drift > 0.1% aborts the publish (same table family, so this is a parsing
    tripwire, not a cross-source validation)
  - B-7 counts suppressed cells and publishes the residual vs the file's own
    State Totals row — the residual is a number on the page, never spread
  - B-7 measures tax ASSESSED (not liability) and includes nonresident /
    unallocated returns: kept as a separate non_geographic list, never dropped
  - the budget_reference block records the waterfall's enacted estimate beside
    the stats total; they measure different years and bases and are expected
    NOT to match — the sanity gate only trips on order-of-magnitude errors
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import UTC, datetime
from typing import Any

from ..config import Settings
from ..publish.envelope import envelope
from ..sources import SourceConfig
from ..storage import Storage, read_manifest, write_manifest
from .csv_download import QualityGateError
from .ebudget_detail import _load_summary
from .http import fetch_bytes

WATERFALL_REVENUE_NAME = "Personal Income Tax"

# B-7 rows that are real money but not places; surfaced separately, never dropped
NON_GEOGRAPHIC = {"Nonresident", "Resident Out-of-State", "Unallocated"}
STATE_TOTALS = "State Totals"

# Presentation bands: B-4A's ~60 granular classes condensed to a readable
# distribution. Pure aggregation by class floor — no estimation. (floor_min,
# floor_max_exclusive, label). Negative/zero AGI handled separately.
BANDS: list[tuple[int, int | None, str]] = [
    (1, 10_000, "$1 – $9,999"),
    (10_000, 20_000, "$10,000 – $19,999"),
    (20_000, 30_000, "$20,000 – $29,999"),
    (30_000, 40_000, "$30,000 – $39,999"),
    (40_000, 50_000, "$40,000 – $49,999"),
    (50_000, 60_000, "$50,000 – $59,999"),
    (60_000, 70_000, "$60,000 – $69,999"),
    (70_000, 80_000, "$70,000 – $79,999"),
    (80_000, 90_000, "$80,000 – $89,999"),
    (90_000, 100_000, "$90,000 – $99,999"),
    (100_000, 150_000, "$100,000 – $149,999"),
    (150_000, 200_000, "$150,000 – $199,999"),
    (200_000, 300_000, "$200,000 – $299,999"),
    (300_000, 400_000, "$300,000 – $399,999"),
    (400_000, 500_000, "$400,000 – $499,999"),
    (500_000, 1_000_000, "$500,000 – $999,999"),
    (1_000_000, 2_000_000, "$1 million – $2 million"),
    (2_000_000, 5_000_000, "$2 million – $5 million"),
    (5_000_000, 10_000_000, "$5 million – $10 million"),
    (10_000_000, None, "$10 million and over"),
]

# B-4A classes at and above this floor become the high-income spotlight tiers
HIGH_INCOME_FLOOR = 1_000_000

# Display bands: the 7-band narrative view the UI leads with (the ~21 fine
# bands stay published for the expandable detail). Same pure aggregation.
# (floor_min or None for "includes negative/zero", floor_max_exclusive, label)
DISPLAY_BANDS: list[tuple[int | None, int | None, str]] = [
    (None, 50_000, "Under $50,000"),
    (50_000, 100_000, "$50,000 – $99,999"),
    (100_000, 200_000, "$100,000 – $199,999"),
    (200_000, 500_000, "$200,000 – $499,999"),
    (500_000, 1_000_000, "$500,000 – $999,999"),
    (1_000_000, 10_000_000, "$1 million – $10 million"),
    (10_000_000, None, "$10 million and over"),
]


# Income composition per band, from B-4A's source-of-income columns:
# (label, gains column, gains returns column, loss column or None).
# Loss columns arrive with INCONSISTENT signs in the source (capital-asset
# losses negative, partnership losses positive), so losses are treated as
# magnitudes and netted; the residual vs FTB's own Total Income line is
# published, never spread.
COMPOSITION_COLS: list[tuple[str, str, str, str | None]] = [
    ("Wages & salaries", "Wages And Salaries", "Returns With Wages and Salaries", None),
    (
        "Capital gains",
        "Net Sale Of Capital Assets Profit",
        "Returns With Net Sale Of Capital Assets Profit",
        "Net Sale Of Capital Assets Loss",
    ),
    (
        "Partnerships & S-corps",
        "Partnerships and S-Corp Gain",
        "Returns With Partnerships and S-Corp Gain",
        "Partnerships and S-Corp Loss",
    ),
    (
        "Business (self-employment)",
        "Business Income Profit",
        "Returns With Business Income Profit",
        "Business Income Loss",
    ),
    (
        "Pensions & annuities",
        "Taxable Pensions And Annuities",
        "Returns With Taxable Pensions And Annuities",
        None,
    ),
    ("Dividends", "Taxable Dividends", "Returns With Taxable Dividends", None),
    ("Interest", "Taxable Interest", "Returns With Taxable Interest", None),
    (
        "Rents & royalties",
        "Rents And Royalties Profit",
        "Returns With Rents And Royalties Profit",
        "Rents and Royalties Loss",
    ),
    (
        "Farm income",
        "Farm Income Profit",
        "Returns With Farm Income Profit",
        "Farm Income Loss",
    ),
    (
        "Estates & trusts",
        "Estates and Trusts Gain",
        "Returns With Estates and Trusts Gain",
        "Estates And Trusts Loss",
    ),
    (
        "All other sources",
        "All Other Federal Income Sources Profit",
        "Returns With All Other Federal Income Sources Profit",
        "All Other Federal Income Sources Loss",
    ),
]

# "Who they are" overlays per band: (key, returns column)
OVERLAY_COLS: list[tuple[str, str]] = [
    ("seniors", "Returns With Senior Or Blind Exemption Credit"),
    ("renters_credit", "Returns With Renter's Credit"),
    ("dependents_credit", "Returns With Dependent Exemption Credit"),
    ("self_employed", "Returns With Half Self-Employment Tax"),
    ("amt", "Returns With Alternative Minimum Tax"),
    ("mental_health_tax", "Returns With Mental Health Tax"),
]


def _num(s: str | None) -> int | None:
    """Parse an FTB numeric cell. Blank/dash/NULL = suppressed -> None, never 0."""
    if s is None:
        return None
    s = s.replace(",", "").strip()
    if s in ("", "-") or s.upper() in ("NULL", "N/A", "NA"):
        return None
    return int(float(s))


def _rows(raw: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))


def _class_floor(agic: str) -> int | None:
    """AGI class label -> band floor in dollars. None = negative/zero AGI."""
    label = agic.strip().lower()
    if label.startswith(("negative", "zero")):
        return None
    m = re.search(r"[\d,]+", agic)
    if not m:
        raise QualityGateError(f"ftb_pit: unparseable AGI class label {agic!r}")
    return int(m.group().replace(",", ""))


def _band_index(floor: int) -> int:
    for i, (lo, hi, _) in enumerate(BANDS):
        if floor >= lo and (hi is None or floor < hi):
            return i
    raise QualityGateError(f"ftb_pit: AGI class floor {floor} fits no presentation band")


def _slug(county: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", county.lower()).strip("-")


def _clean_label(agic: str) -> str:
    """Normalize FTB class labels ('1,000,000  to  1,999,999' -> '$1,000,000 to $1,999,999')."""
    label = re.sub(r"\s+", " ", agic).strip()
    return re.sub(r"(?<![\d$])([\d][\d,]*)", r"$\1", label)


def run_ftb_pit(storage: Storage, cfg: SourceConfig, settings: Settings) -> list[str]:
    now = datetime.now(UTC)
    as_of = now.strftime("%Y-%m-%dT%H%M%SZ")
    manifest = read_manifest(storage, cfg.source)

    raw = {name: fetch_bytes(url) for name, url in cfg.endpoints.items()}

    content_hash = hashlib.sha256(b"".join(raw[k] for k in sorted(raw))).hexdigest()
    if manifest.get("content_hash") == content_hash:
        manifest["checked_at"] = now.isoformat()
        write_manifest(storage, cfg.source, manifest)
        print(f"{cfg.source}: unchanged upstream, no-op")
        return manifest.get("published_keys", [])

    for name, blob in raw.items():
        storage.put_bytes(f"raw/{cfg.source}/{cfg.dataset}/{as_of}/{name}.csv", blob, "text/csv")

    doc, zip_docs = build_pit_docs(
        b4a=_rows(raw["b4a"]),
        b3=_rows(raw["b3"]),
        b7=_rows(raw["b7"]),
        zips=_rows(raw["zip"]),
        waterfall=_load_summary(storage),
        min_rows=cfg.min_rows,
    )

    published_keys = []
    for key, payload in [("published/revenue/pit.json", doc)] + [
        (f"published/revenue/pit_zip/{slug}.json", zdoc) for slug, zdoc in sorted(zip_docs.items())
    ]:
        storage.put_bytes(
            key,
            json.dumps(
                envelope(cfg, as_of=as_of, ingested_at=now.isoformat(), data=payload), indent=2
            ).encode(),
            "application/json",
        )
        published_keys.append(key)

    write_manifest(
        storage,
        cfg.source,
        {
            "content_hash": content_hash,
            "row_count": len(doc["brackets"]) + len(doc["counties"]),
            "as_of": as_of,
            "ingested_at": now.isoformat(),
            "checked_at": now.isoformat(),
            "published_keys": published_keys,
        },
    )
    print(
        f"{cfg.source}: TY{doc['tax_year']} — {len(doc['brackets'])} bands, "
        f"{len(doc['counties'])} counties, {len(zip_docs)} ZIP files"
    )
    return published_keys


def build_pit_docs(
    b4a: list[dict[str, str]],
    b3: list[dict[str, str]],
    b7: list[dict[str, str]],
    zips: list[dict[str, str]],
    waterfall: dict[str, Any],
    min_rows: int = 40,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    tax_year = max(int(r["Taxable Year"]) for r in b4a)
    classes = [r for r in b4a if int(r["Taxable Year"]) == tax_year]
    if len(classes) < min_rows:
        raise QualityGateError(f"ftb_pit: only {len(classes)} B-4A classes for {tax_year}")

    # ---- statewide + presentation bands (B-4A) ----
    negative_zero = {"returns": 0, "agi_usd": 0, "tax_liability_usd": 0}
    bands = [
        {
            "label": label,
            "floor_usd": lo,
            "ceiling_usd": hi,
            "returns": 0,
            "agi_usd": 0,
            "tax_liability_usd": 0,
        }
        for lo, hi, label in BANDS
    ]
    high_income = []
    for r in classes:
        floor = _class_floor(r["AGIC"])
        returns = _num(r["All Returns"]) or 0
        agi = _num(r["California AGI"]) or 0
        tax = _num(r["Total Tax Liability"]) or 0
        if floor is None:
            for k, v in [("returns", returns), ("agi_usd", agi), ("tax_liability_usd", tax)]:
                negative_zero[k] += v
        else:
            b = bands[_band_index(floor)]
            b["returns"] += returns
            b["agi_usd"] += agi
            b["tax_liability_usd"] += tax
        if floor is not None and floor >= HIGH_INCOME_FLOOR:
            high_income.append(
                {
                    "label": _clean_label(r["AGIC"]),
                    "floor_usd": floor,
                    "returns": returns,
                    "tax_liability_usd": tax,
                }
            )
    high_income.sort(key=lambda t: t["floor_usd"])

    total_tax = negative_zero["tax_liability_usd"] + sum(b["tax_liability_usd"] for b in bands)
    total_returns = negative_zero["returns"] + sum(b["returns"] for b in bands)
    total_agi = negative_zero["agi_usd"] + sum(b["agi_usd"] for b in bands)

    # tripwire: B-3 publishes the same totals independently (same table family —
    # this validates parsing, not the source)
    b3_latest = [r for r in b3 if int(r["Taxable Year"]) == tax_year]
    b3_tax = sum(_num(r["Total Tax Liability"]) or 0 for r in b3_latest)
    if b3_tax and abs(b3_tax - total_tax) / b3_tax > 0.001:
        raise QualityGateError(
            f"ftb_pit: B-4A total tax {total_tax} vs B-3 {b3_tax} — parsing drift, "
            "refusing to publish"
        )

    all_bands = [
        {"label": "Negative or zero AGI", "floor_usd": None, "ceiling_usd": 0, **negative_zero}
    ] + bands
    cum_from_top = 0
    for b in reversed(all_bands):
        cum_from_top += b["tax_liability_usd"]
        b["cum_share_of_tax_pct"] = round(cum_from_top / total_tax * 100, 2) if total_tax else 0
    for b in all_bands:
        b["share_of_tax_pct"] = (
            round(b["tax_liability_usd"] / total_tax * 100, 2) if total_tax else 0
        )
        b["share_of_returns_pct"] = (
            round(b["returns"] / total_returns * 100, 2) if total_returns else 0
        )
        b["avg_tax_usd"] = round(b["tax_liability_usd"] / b["returns"]) if b["returns"] else 0
    for t in high_income:
        t["share_of_tax_pct"] = (
            round(t["tax_liability_usd"] / total_tax * 100, 2) if total_tax else 0
        )

    # condensed display bands: aggregate the fine bands by floor range, then
    # enrich each with income composition + "who they are" overlays summed
    # straight from the raw B-4A class rows in the same floor range
    def _display_index(floor: int | None) -> int:
        for i, (lo, hi, _) in enumerate(DISPLAY_BANDS):
            if floor is None:
                if lo is None:
                    return i
            elif (lo is None or floor >= lo) and (hi is None or floor < hi):
                return i
        raise QualityGateError(f"ftb_pit: class floor {floor} fits no display band")

    display_bands = []
    for lo, hi, label in DISPLAY_BANDS:
        members = [
            b
            for b in all_bands
            if (b["floor_usd"] is None and lo is None)
            or (
                b["floor_usd"] is not None
                and (lo is None or b["floor_usd"] >= lo)
                and (hi is None or b["floor_usd"] < hi)
            )
        ]
        returns = sum(b["returns"] for b in members)
        tax = sum(b["tax_liability_usd"] for b in members)
        display_bands.append(
            {
                "label": label,
                "returns": returns,
                "tax_liability_usd": tax,
                "avg_tax_usd": round(tax / returns) if returns else 0,
                "share_of_returns_pct": (
                    round(returns / total_returns * 100, 2) if total_returns else 0
                ),
                "share_of_tax_pct": round(tax / total_tax * 100, 2) if total_tax else 0,
                "composition": [
                    {"source": lbl, "usd": 0, "returns": 0}
                    for lbl, _, _, _ in COMPOSITION_COLS
                ],
                "itemized_income_usd": 0,
                "total_income_usd": 0,
                "overlays": {key: 0 for key, _ in OVERLAY_COLS}
                | {"mental_health_tax_usd": 0},
            }
        )
    for r in classes:
        d = display_bands[_display_index(_class_floor(r["AGIC"]))]
        for i, (_, gain_col, gain_returns_col, loss_col) in enumerate(COMPOSITION_COLS):
            net = _num(r[gain_col]) or 0
            if loss_col is not None:
                # source sign conventions are inconsistent; losses are magnitudes
                net -= abs(_num(r[loss_col]) or 0)
            d["composition"][i]["usd"] += net
            d["composition"][i]["returns"] += _num(r[gain_returns_col]) or 0
            d["itemized_income_usd"] += net
        d["total_income_usd"] += _num(r["Total Income"]) or 0
        for key, col in OVERLAY_COLS:
            d["overlays"][key] += _num(r[col]) or 0
        d["overlays"]["mental_health_tax_usd"] += _num(r["Mental Health Tax"]) or 0
    for d in display_bands:
        d["composition"].sort(key=lambda c: -c["usd"])
        denom = d["itemized_income_usd"]
        for c in d["composition"]:
            c["share_of_income_pct"] = round(c["usd"] / denom * 100, 1) if denom > 0 else 0
        # overlay counts can never exceed the band's returns (parsing tripwire)
        for key, _ in OVERLAY_COLS:
            if d["overlays"][key] > d["returns"]:
                raise QualityGateError(
                    f"ftb_pit: overlay {key} count {d['overlays'][key]} exceeds "
                    f"band returns {d['returns']}"
                )
        # itemized composition should land near FTB's own Total Income line;
        # drift beyond 10% means the column map went stale
        if d["total_income_usd"] > 0:
            drift = abs(d["itemized_income_usd"] - d["total_income_usd"]) / d["total_income_usd"]
            if drift > 0.10:
                raise QualityGateError(
                    f"ftb_pit: band {d['label']!r} itemized income drifts "
                    f"{drift:.1%} from Total Income — stale column map"
                )
    if sum(b["returns"] for b in display_bands) != total_returns or sum(
        b["tax_liability_usd"] for b in display_bands
    ) != total_tax:
        raise QualityGateError("ftb_pit: display bands do not partition the fine bands")

    # ---- counties (B-7, tax ASSESSED) ----
    b7_year = max(int(r["Taxable Year"]) for r in b7)
    b7_latest = [r for r in b7 if int(r["Taxable Year"]) == b7_year]
    counties: dict[str, dict[str, Any]] = {}
    non_geographic: dict[str, dict[str, int]] = {}
    state_totals = {"returns": 0, "tax_assessed_usd": 0}
    for r in b7_latest:
        name = r["County"].strip()
        returns, agi, tax = (
            _num(r["All Returns"]),
            _num(r["Adjusted Gross Income"]),
            _num(r["Tax Assessed"]),
        )
        if name == STATE_TOTALS:
            state_totals["returns"] += returns or 0
            state_totals["tax_assessed_usd"] += tax or 0
            continue
        if name in NON_GEOGRAPHIC:
            g = non_geographic.setdefault(name, {"returns": 0, "tax_assessed_usd": 0})
            g["returns"] += returns or 0
            g["tax_assessed_usd"] += tax or 0
            continue
        c = counties.setdefault(
            name,
            {
                "county": name,
                "returns": 0,
                "agi_usd": 0,
                "tax_assessed_usd": 0,
                "brackets": [],
                "suppressed_cells": 0,
            },
        )
        c["brackets"].append(
            {
                "label": _clean_label(r["AGIC"]),
                "returns": returns,
                "agi_usd": agi,
                "tax_assessed_usd": tax,
            }
        )
        if returns is None or tax is None:
            c["suppressed_cells"] += 1
        c["returns"] += returns or 0
        c["agi_usd"] += agi or 0
        c["tax_assessed_usd"] += tax or 0

    if len(counties) != 58:
        raise QualityGateError(f"ftb_pit: B-7 has {len(counties)} counties, expected 58")
    for c in counties.values():
        c["per_return_tax_usd"] = round(c["tax_assessed_usd"] / c["returns"]) if c["returns"] else 0

    counties_sum = sum(c["tax_assessed_usd"] for c in counties.values()) + sum(
        g["tax_assessed_usd"] for g in non_geographic.values()
    )
    residual = state_totals["tax_assessed_usd"] - counties_sum
    if (
        state_totals["tax_assessed_usd"]
        and abs(residual) / state_totals["tax_assessed_usd"] > 0.005
    ):
        raise QualityGateError(
            f"ftb_pit: B-7 counties sum {counties_sum} vs State Totals "
            f"{state_totals['tax_assessed_usd']} — drift beyond suppression slack"
        )

    # ---- budget reference (expected mismatch, sanity-banded only) ----
    rev = next(
        (r for r in waterfall["general_fund"]["revenue"] if r["name"] == WATERFALL_REVENUE_NAME),
        None,
    )
    if rev is None:
        raise QualityGateError(f"ftb_pit: waterfall has no revenue item {WATERFALL_REVENUE_NAME!r}")
    ratio = total_tax / rev["usd"] if rev["usd"] else 0
    if not 0.5 <= ratio <= 1.5:
        raise QualityGateError(
            f"ftb_pit: TY{tax_year} total {total_tax} vs waterfall {rev['usd']} — "
            f"ratio {ratio:.2f} outside sanity band, likely a units error"
        )

    # ---- per-county ZIP docs (more recent tax year, CA only) ----
    zip_year = max(int(r["TaxYear"]) for r in zips)
    zip_latest = [r for r in zips if int(r["TaxYear"]) == zip_year and r["State"].strip() == "CA"]
    zip_docs: dict[str, dict[str, Any]] = {}
    zip_total_tax = 0
    for r in zip_latest:
        county = r["County"].strip()
        if county not in counties:
            continue  # rows FTB attributes to no CA county; counted in coverage note
        slug = _slug(county)
        d = zip_docs.setdefault(
            slug, {"county": county, "tax_year": zip_year, "total_tax_liability_usd": 0, "zips": []}
        )
        tax = _num(r["TotalTaxLiability"]) or 0
        d["zips"].append(
            {
                "zip": r["ZipCode"].strip(),
                "city": r["City"].strip(),
                "returns": _num(r["Returns"]),
                "agi_usd": _num(r["CAAGI"]),
                "tax_liability_usd": tax,
            }
        )
        d["total_tax_liability_usd"] += tax
        zip_total_tax += tax
    for d in zip_docs.values():
        d["zips"].sort(key=lambda z: -(z["tax_liability_usd"] or 0))
    if len(zip_docs) < 50:
        raise QualityGateError(f"ftb_pit: ZIP table covers only {len(zip_docs)} counties")

    doc = {
        "tax_year": tax_year,
        "budget_reference": {
            "budget_year": waterfall.get("budget_year"),
            "waterfall_usd": rev["usd"],
            "stats_total_usd": total_tax,
            "note": (
                "The budget waterfall shows the Department of Finance's enacted revenue "
                f"estimate for {waterfall.get('budget_year')}. The figures below are what "
                f"taxpayers actually reported for tax year {tax_year}, the latest FTB has "
                "published — different years and different measures, shown side by side "
                "rather than stretched to fit."
            ),
        },
        "statewide": {
            "returns": total_returns,
            "agi_usd": total_agi,
            "tax_liability_usd": total_tax,
        },
        "brackets": all_bands,
        "display_bands": display_bands,
        "high_income": high_income,
        "counties": sorted(counties.values(), key=lambda c: -c["tax_assessed_usd"]),
        "non_geographic": [
            {"label": k, **v}
            for k, v in sorted(non_geographic.items(), key=lambda kv: -kv[1]["tax_assessed_usd"])
        ],
        "county_tax_year": b7_year,
        "county_measure_note": (
            "County figures are tax assessed (B-7), a different measure from the tax "
            "liability in the statewide brackets (B-4A). Returns FTB cannot place in a "
            "county — nonresidents, residents out of state, unallocated — are listed "
            "separately, not dropped."
        ),
        "county_cross_check": {
            "state_totals_usd": state_totals["tax_assessed_usd"],
            "counties_sum_usd": counties_sum,
            "suppression_residual_usd": residual,
        },
        "zip_tax_year": zip_year,
        "zip_coverage": {
            "counties": len(zip_docs),
            "zips": sum(len(d["zips"]) for d in zip_docs.values()),
            "listed_total_tax_usd": zip_total_tax,
            "note": (
                "ZIPs below FTB's disclosure threshold are omitted by the source, so "
                "listed ZIPs sum to less than the statewide total."
            ),
        },
    }
    return doc, zip_docs

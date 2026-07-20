"""FTB Corporation Tax statistics: which industries and income classes pay it.

Publishes published/revenue/corp.json from three FTB CSVs (data.ca.gov):
  C-10  — tax liability by industry, all corporations (WIDE format: one row
          per year, industries as column triplets)
  C-10A/B — same, split C vs S corporations
  C-8   — tax assessed by state-net-income class (long format)

Fail-honest rules:
  - only LEAF industry columns are summed (the file also carries subtotal
    columns like "Total Manufacturing"); the leaf sum must reconcile with the
    file's own all-industry total within 0.5% or the publish aborts
  - C-10 measures tax LIABILITY, C-8 tax ASSESSED — different measures, both
    published with their own totals, never blended
  - the C/S split per industry is published as reported; small mismatches vs
    the all-corporation column are the source's own rounding, disclosed via
    the reconciliation block
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

WATERFALL_REVENUE_NAME = "Corporation Tax"

# Leaf industries in the C-10 wide format: (display label, returns col,
# net-income col, tax col). Subtotal columns (Total Manufacturing, Total
# Services, Total Trade, Total FIRE) are deliberately NOT listed — summing
# them would double-count.
INDUSTRY_COLS: list[tuple[str, str, str, str]] = [
    (
        "Agriculture, forestry & fishing",
        "Rtns Reporting Tax Liability in Agriculture/Forestry/Fishing",
        "Agriculture Forestry and Fishing Net Income Less Net Loss",
        "Agriculture Forestry and Fishing Total Tax",
    ),
    (
        "Mining",
        "Returns Reporting Tax Liability In Mining",
        "Mining Net Income Less Net Loss",
        "Mining Total Tax",
    ),
    (
        "Construction",
        "Returns Reporting Tax Liability In Construction",
        "Construction Net Income Less Net Loss",
        "Construction Total Tax",
    ),
    (
        "Durable goods manufacturing",
        "Rtns Reporting Tax Liability in Durable Goods Mfg.",
        "Durable Goods Manufacturing Net Income Less Net Loss",
        "Durable Goods Manufacturing Total Tax",
    ),
    (
        "Nondurable goods manufacturing",
        "Rtns Reporting Tax Liability in Nondurable Goods Mfg.",
        "Nondurable Goods Manufacturing Net Income Less Net Loss",
        "Nondurable Goods Manufacturing Total Tax",
    ),
    (
        "Professional, scientific & technical services",
        "Rtns Reporting Tax Liability in Prof./Sci./Tech. Svcs.",
        "Prof./Sci./Tech. Svcs. Net Income Less Net Loss",
        "Professional Scientific and Technical Services Total Tax",
    ),
    (
        "Administrative services",
        "Returns Reporting Tax Liability In Administrative Services",
        "Administrative Services Net Income Less Net Loss",
        "Administrative Services Total Tax",
    ),
    (
        "Accommodation & food services",
        "Rtns Reporting Tax Liability in Accommodation and Food Svcs.",
        "Accommodation and Food Services Net Income Less Net Loss",
        "Accommodation and Food Services Total Tax",
    ),
    (
        "Arts, entertainment & recreation",
        "Rtns Reporting Tax Liability in Arts Entmt/Rec Svcs.",
        "Arts Entmt/ Rec. Svcs. Net Income Less Net Loss",
        "Arts Entertainment and Recreation Services Total Tax",
    ),
    (
        "Health services",
        "Returns Reporting Tax Liability In Health Services",
        "Health Services Net Income Less Net Loss",
        "Health Services Total Tax",
    ),
    (
        "Other services",
        "Returns Reporting Tax Liability In Other Services",
        "Other Services Net Income Less Net Loss",
        "Other Services Total Tax",
    ),
    (
        "Wholesale trade",
        "Returns Reporting Tax Liability In Wholesale Trade",
        "Wholesale Trade Net Income Less Net Loss",
        "Wholesale Trade Total Tax",
    ),
    (
        "Retail trade",
        "Returns Reporting Tax Liability In Retail Trade",
        "Retail Trade Net Income Less Net Loss",
        "Retail Trade Total Tax",
    ),
    (
        "Finance, investment & insurance",
        "Rtns Reporting Tax Liability in Financ. Invest./Ins.",
        "Finance Investment and Insurance Net Income Less Net Loss",
        "Finance Investment and Insurance Total Tax",
    ),
    (
        "Holding companies",
        "Returns Reporting Tax Liability In Holding Companies",
        "Holding Companies Net Income Less Net Loss",
        "Holding Companies Total Tax",
    ),
    (
        "Real estate",
        "Returns Reporting Tax Liability In Real Estate",
        "Real Estate Net Income Less Net Loss",
        "Real Estate Net Income Total Tax",
    ),
    (
        "Transportation, warehousing & utilities",
        "Rtns Reporting Tax Liability in Trans. Whs/ Utilities",
        "Trans. Whs./Utilities Net Income Less Net Loss",
        "Transportation Warehousing and Utilities Total Tax",
    ),
    (
        "Information & communications",
        "Rtns. Reporting Tax Liablilty in Infor./Comm.",
        "Information and Communications Net Income Less Net Loss",
        "Information and Communications Total Tax",
    ),
    (
        "Unknown industry",
        "Returns Reporting Tax Liability in Unknown",
        "Unknown Net Income Less Net Loss",
        "Unknown Total Tax",
    ),
]

TOTAL_COLS = (
    "Ttl. Rtns. For All Industry Categories with Tax Liability",
    "Total Net Income Less Net Loss For All Industry Categories",
    "Total Tax For All Industry Categories",
)


def _num(s: str | None) -> int | None:
    if s is None:
        return None
    s = s.replace(",", "").strip()
    if s in ("", "-"):
        return None
    return int(float(s))


def _rows(raw: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))


def _class_sort_key(label: str) -> tuple[int, int]:
    """C-8 income classes arrive out of order; sort Net Loss / No Income first,
    then by class floor."""
    low = label.strip().lower()
    if low.startswith("net loss"):
        return (0, 0)
    if low.startswith("no income"):
        return (1, 0)
    m = re.search(r"[\d,]+", label)
    return (2, int(m.group().replace(",", "")) if m else 0)


def _clean_class_label(label: str) -> str:
    label = re.sub(r"\s+", " ", label).strip()
    return re.sub(r"(?<![\d$])([\d][\d,]*)", r"$\1", label)


def run_ftb_corp(storage: Storage, cfg: SourceConfig, settings: Settings) -> list[str]:
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

    doc = build_corp_doc(
        c10=_rows(raw["c10"]),
        c10ab=_rows(raw["c10ab"]),
        c8=_rows(raw["c8"]),
        waterfall=_load_summary(storage),
        min_rows=cfg.min_rows,
    )

    key = "published/revenue/corp.json"
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
            "row_count": len(doc["industries"]) + len(doc["income_classes"]),
            "as_of": as_of,
            "ingested_at": now.isoformat(),
            "checked_at": now.isoformat(),
            "published_keys": [key],
        },
    )
    print(
        f"{cfg.source}: TY{doc['tax_year']} — {len(doc['industries'])} industries, "
        f"{len(doc['income_classes'])} income classes"
    )
    return [key]


def build_corp_doc(
    c10: list[dict[str, str]],
    c10ab: list[dict[str, str]],
    c8: list[dict[str, str]],
    waterfall: dict[str, Any],
    min_rows: int = 15,
) -> dict[str, Any]:
    tax_year = max(int(r["Taxable Year"]) for r in c10)
    year_row = next(r for r in c10 if int(r["Taxable Year"]) == tax_year)
    cs_rows = {
        r["Corporation Type"].strip(): r
        for r in c10ab
        if int(r["Taxable Year"]) == tax_year
    }

    total_returns = _num(year_row[TOTAL_COLS[0]]) or 0
    total_net_income = _num(year_row[TOTAL_COLS[1]]) or 0
    total_tax = _num(year_row[TOTAL_COLS[2]]) or 0
    if not total_tax:
        raise QualityGateError(f"ftb_corp: C-10 all-industry total missing for {tax_year}")

    industries = []
    for label, rtn_col, ni_col, tax_col in INDUSTRY_COLS:
        tax = _num(year_row[tax_col]) or 0
        industries.append(
            {
                "industry": label,
                "returns": _num(year_row[rtn_col]),
                "net_income_usd": _num(year_row[ni_col]),
                "tax_liability_usd": tax,
                "share_of_tax_pct": round(tax / total_tax * 100, 2),
                "c_corp_tax_usd": _num(cs_rows["C"][tax_col]) if "C" in cs_rows else None,
                "s_corp_tax_usd": _num(cs_rows["S"][tax_col]) if "S" in cs_rows else None,
            }
        )
    industries.sort(key=lambda i: -i["tax_liability_usd"])
    if len(industries) < min_rows:
        raise QualityGateError(f"ftb_corp: only {len(industries)} industries parsed")

    leaf_sum = sum(i["tax_liability_usd"] for i in industries)
    if abs(leaf_sum - total_tax) / total_tax > 0.005:
        raise QualityGateError(
            f"ftb_corp: leaf industries sum {leaf_sum} vs file total {total_tax} — "
            "column map is stale, refusing to publish"
        )

    # ---- C-8 income classes (tax ASSESSED, a different measure) ----
    c8_year = max(int(r["Taxable Year"]) for r in c8)
    c8_rows = sorted(
        (r for r in c8 if int(r["Taxable Year"]) == c8_year),
        key=lambda r: _class_sort_key(r["CA SNI Taxable Range"]),
    )
    if len(c8_rows) < min_rows:
        raise QualityGateError(f"ftb_corp: only {len(c8_rows)} C-8 classes for {c8_year}")
    c8_total = sum(_num(r["Tax Assessed"]) or 0 for r in c8_rows)
    income_classes = []
    for r in c8_rows:
        tax = _num(r["Tax Assessed"]) or 0
        income_classes.append(
            {
                "label": _clean_class_label(r["CA SNI Taxable Range"]),
                "returns": _num(r["Returns With SNI"]),
                "net_income_usd": _num(r["Net Income Less Net Loss"]),
                "tax_assessed_usd": tax,
                "share_of_tax_pct": round(tax / c8_total * 100, 2) if c8_total else 0,
            }
        )

    # condensed display classes: the 5-group narrative view the UI leads with
    display_groups: list[tuple[str, Any]] = [
        ("Reported a loss or no income", lambda k, f: k < 2),
        ("Under $100,000", lambda k, f: k == 2 and f < 100_000),
        ("$100,000 – $999,999", lambda k, f: k == 2 and 100_000 <= f < 1_000_000),
        ("$1 million – $10 million", lambda k, f: k == 2 and 1_000_000 <= f < 10_000_000),
        ("$10 million and over", lambda k, f: k == 2 and f >= 10_000_000),
    ]
    total_c8_returns = sum(c["returns"] or 0 for c in income_classes)
    display_classes = []
    for label, member in display_groups:
        rows_in = [
            c for c in income_classes if member(*_class_sort_key(c["label"]))
        ]
        returns = sum(c["returns"] or 0 for c in rows_in)
        tax = sum(c["tax_assessed_usd"] for c in rows_in)
        display_classes.append(
            {
                "label": label,
                "returns": returns,
                "tax_assessed_usd": tax,
                "share_of_returns_pct": (
                    round(returns / total_c8_returns * 100, 2) if total_c8_returns else 0
                ),
                "share_of_tax_pct": round(tax / c8_total * 100, 2) if c8_total else 0,
            }
        )
    if sum(c["tax_assessed_usd"] for c in display_classes) != c8_total:
        raise QualityGateError("ftb_corp: display classes do not partition the C-8 classes")

    # ---- budget reference: expected mismatch, sanity-banded only ----
    rev = next(
        (r for r in waterfall["general_fund"]["revenue"] if r["name"] == WATERFALL_REVENUE_NAME),
        None,
    )
    if rev is None:
        raise QualityGateError(
            f"ftb_corp: waterfall has no revenue item {WATERFALL_REVENUE_NAME!r}"
        )
    ratio = total_tax / rev["usd"] if rev["usd"] else 0
    if not 0.4 <= ratio <= 1.6:
        raise QualityGateError(
            f"ftb_corp: TY{tax_year} total {total_tax} vs waterfall {rev['usd']} — "
            f"ratio {ratio:.2f} outside sanity band, likely a units error"
        )

    return {
        "tax_year": tax_year,
        "budget_reference": {
            "budget_year": waterfall.get("budget_year"),
            "waterfall_usd": rev["usd"],
            "stats_total_usd": total_tax,
            "note": (
                "The budget waterfall shows the Department of Finance's enacted revenue "
                f"estimate for {waterfall.get('budget_year')}. The figures below are what "
                f"corporations actually reported for tax year {tax_year}, the latest FTB "
                "has published — different years and different measures, shown side by "
                "side rather than stretched to fit."
            ),
        },
        "statewide": {
            "returns_with_liability": total_returns,
            "net_income_usd": total_net_income,
            "tax_liability_usd": total_tax,
        },
        "industries": industries,
        "industry_reconciliation": {
            "leaf_sum_usd": leaf_sum,
            "file_total_usd": total_tax,
        },
        "income_classes": income_classes,
        "display_classes": display_classes,
        "income_class_tax_year": c8_year,
        "income_class_measure_note": (
            "Income classes (C-8) report tax assessed; the industry table (C-10) reports "
            "tax liability. Different measures — their totals differ by design."
        ),
        "income_class_total_usd": c8_total,
    }

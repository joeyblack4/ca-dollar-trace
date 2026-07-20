"""ftb_corp + sec_state_tax builder tests: wide-format parsing, reconciliation
gates, and the SEC plausibility screen."""

import pytest

from cadollar.ingest.csv_download import QualityGateError
from cadollar.ingest.ftb_corp import INDUSTRY_COLS, TOTAL_COLS, build_corp_doc
from cadollar.ingest.sec_state_tax import screen_companies


def _c10_row(year, per_industry_tax=1_000_000, corp_type=None):
    row = {"Taxable Year": str(year)}
    if corp_type:
        row["Corporation Type"] = corp_type
    for _, rtn_col, ni_col, tax_col in INDUSTRY_COLS:
        row[rtn_col] = "100"
        row[ni_col] = "5,000,000"
        row[tax_col] = f"{per_industry_tax:,}"
    row[TOTAL_COLS[0]] = f"{100 * len(INDUSTRY_COLS):,}"
    row[TOTAL_COLS[1]] = f"{5_000_000 * len(INDUSTRY_COLS):,}"
    row[TOTAL_COLS[2]] = f"{per_industry_tax * len(INDUSTRY_COLS):,}"
    return row


def _c8(year=2022):
    ranges = [
        ("Net Loss", 500),
        ("No Income or Loss", 100),
        ("1 to 4,999", 50),
        ("5,000 to 9,999", 60),
        ("10,000,000 and over", 10_000),
        ("100,000 to 149,999", 400),
    ]
    rows = []
    for label, tax in ranges:
        rows.append(
            {
                "Taxable Year": str(year),
                "CA SNI Taxable Range": label,
                "Returns With SNI": "1,000",
                "Net Income Less Net Loss": "9,000",
                "Tax Assessed": f"{tax:,}",
            }
        )
    return rows


TOTAL_TAX = 1_000_000 * len(INDUSTRY_COLS)


def _waterfall(usd=TOTAL_TAX):
    return {
        "budget_year": "2025-26",
        "general_fund": {"revenue": [{"name": "Corporation Tax", "usd": usd}]},
    }


def build(**overrides):
    kwargs = dict(
        c10=[_c10_row(2022), _c10_row(2021, per_industry_tax=999)],
        c10ab=[_c10_row(2022, 600_000, "C"), _c10_row(2022, 400_000, "S")],
        c8=_c8(),
        waterfall=_waterfall(),
        min_rows=5,
    )
    kwargs.update(overrides)
    return build_corp_doc(**kwargs)


def test_wide_format_parsed_with_cs_split():
    doc = build()
    assert doc["tax_year"] == 2022
    assert len(doc["industries"]) == len(INDUSTRY_COLS)
    first = doc["industries"][0]
    assert first["tax_liability_usd"] == 1_000_000
    assert first["c_corp_tax_usd"] == 600_000
    assert first["s_corp_tax_usd"] == 400_000
    assert doc["statewide"]["tax_liability_usd"] == TOTAL_TAX
    assert doc["industry_reconciliation"]["leaf_sum_usd"] == TOTAL_TAX


def test_stale_column_map_refuses_to_publish():
    c10 = [_c10_row(2022)]
    c10[0][TOTAL_COLS[2]] = f"{TOTAL_TAX * 2:,}"  # file total no longer matches leaves
    with pytest.raises(QualityGateError, match="column map is stale"):
        build(c10=c10, waterfall=_waterfall(TOTAL_TAX * 2))


def test_income_classes_sorted_and_labeled():
    doc = build()
    labels = [c["label"] for c in doc["income_classes"]]
    # Net Loss and No Income first, then ascending by floor; source order was shuffled
    assert labels[0] == "Net Loss"
    assert labels[1] == "No Income or Loss"
    assert labels[2] == "$1 to $4,999"
    assert labels[-1] == "$10,000,000 and over"
    assert doc["income_classes"][-1]["share_of_tax_pct"] == pytest.approx(
        10_000 / 11_110 * 100, abs=0.01
    )


def test_sanity_band_trips_on_units_error():
    with pytest.raises(QualityGateError, match="sanity band"):
        build(waterfall=_waterfall(TOTAL_TAX * 1000))


# ---------- SEC plausibility screen ----------


def test_screen_drops_tagging_errors_and_counts_them():
    rows = [
        {"cik": 1, "entityName": "Real Corp", "val": 2_000_000_000},
        {"cik": 2, "entityName": "Mistagged Inc", "val": 3_000_000_000},  # total ~0
        {"cik": 3, "entityName": "No Total Co", "val": 50_000_000},  # nothing to check against
        {"cik": 4, "entityName": "Benefit Corp", "val": -5_000_000},  # tax benefit
    ]
    totals = {1: 12_000_000_000, 2: 100_000, 4: 1_000_000}
    kept, excluded = screen_companies(rows, totals)
    assert [r["cik"] for r in kept] == [1]
    assert excluded == 2  # mistagged + unverifiable; the benefit row is skipped, not "excluded"


def test_screen_allows_state_tax_despite_small_total():
    # small but plausible: state 8M vs total 1M is within 10x + 5M floor
    rows = [{"cik": 9, "entityName": "Edge Co", "val": 8_000_000}]
    kept, excluded = screen_companies(rows, {9: 1_000_000})
    assert len(kept) == 1 and excluded == 0

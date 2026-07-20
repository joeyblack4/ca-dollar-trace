"""cdtfa_sales builder tests: partition rule, county/city split, suppression."""

import pytest

from cadollar.ingest.cdtfa_sales import build_sales_doc
from cadollar.ingest.csv_download import QualityGateError

QUARTERS = [(2025, "Q2"), (2025, "Q3"), (2025, "Q4"), (2026, "Q1")]


def _biz_rows():
    rows = []
    for y, q in QUARTERS:
        # group head + child (child must NOT be counted)
        rows.append(_biz(y, q, "Motor Vehicle and Parts Dealers - Group",
                         "Motor Vehicle and Parts Dealers", "441", 60))
        rows.append(_biz(y, q, "Motor Vehicle and Parts Dealers - Group",
                         "New Car Dealers", "44111", 45))
        # single-row category
        rows.append(_biz(y, q, "Gasoline Stations", "Gasoline Stations", "447", 30))
        # all-other leaf
        rows.append(_biz(y, q, "All Other Outlets", "Manufacturing", "31 - 33", 10))
        # file's own total = heads + all-other
        rows.append(_biz(y, q, "Total All Outlets", "Total All Outlets", None, 100))
    return rows


def _biz(y, q, cat, typ, naics, amount):
    return {
        "CalendarYear": y,
        "Quarter": q,
        "BusinessTypeCategory": cat,
        "BusinessType": typ,
        "NAICS": naics,
        "NumberOfPermits": 7,
        "TaxableTransactionsAmount": amount,
    }


def _city_rows():
    rows = []
    for y, q in QUARTERS:
        for county in [f"C{i:02d}" for i in range(57)]:
            rows.append(_city(y, q, f"{county} COUNTY".upper(), county, 1))
            rows.append(_city(y, q, f"Town of {county}", county, 1))
        rows.append(_city(y, q, "SAN FRANCISCO", "San Francisco", 43))
        # suppressed city: no amount, flag set
        rows.append(_city(y, q, "Tinyville", "C00", None, flag="D"))
    return rows


def _city(y, q, city, county, amount, flag=None):
    return {
        "CalendarYear": y,
        "Quarter": q,
        "City": city,
        "County": county,
        "TotalAllOutletsTaxableTransactions": amount,
        "DisclosureFlag": flag,
    }


def _sumrev():
    rows = []
    for fy, gf in [(2023, 90), (2024, 100), (2025, 0)]:  # 2025 = placeholder year
        rows.append({"FiscalYearFrom": fy, "FiscalYearTo": fy + 1,
                     "TaxProgramGroup": "State taxes", "TaxProgram": "State taxes",
                     "RevenueAccount": "General Fund", "Revenue": gf})
        rows.append({"FiscalYearFrom": fy, "FiscalYearTo": fy + 1,
                     "TaxProgramGroup": "Public safety fund sales tax",
                     "TaxProgram": "Public safety fund sales tax",
                     "RevenueAccount": "Public Safety Fund", "Revenue": 40})
    return rows


def _waterfall(usd=100):
    return {
        "budget_year": "2025-26",
        "general_fund": {"revenue": [{"name": "Sales and Use Tax", "usd": usd}]},
    }


def build(**overrides):
    kwargs = dict(
        biz=_biz_rows(),
        city=_city_rows(),
        sumrev=_sumrev(),
        waterfall=_waterfall(),
        min_rows=3,
        min_cities=10,
    )
    kwargs.update(overrides)
    return build_sales_doc(**kwargs)


def test_partition_excludes_children_and_reconciles():
    doc = build()
    labels = [t["label"] for t in doc["business_types"]]
    assert "Motor Vehicle and Parts Dealers" in labels
    assert "New Car Dealers" not in labels  # child of a group head
    assert doc["business_type_reconciliation"]["partition_sum_usd"] == 400
    assert doc["business_type_reconciliation"]["total_all_outlets_usd"] == 400
    assert doc["latest_quarter"] == "2026-Q1"


def test_stale_partition_rule_refuses_to_publish():
    rows = _biz_rows()
    for r in rows:  # inflate the file total so the partition no longer matches
        if r["BusinessTypeCategory"] == "Total All Outlets":
            r["TaxableTransactionsAmount"] = 500
    with pytest.raises(QualityGateError, match="hierarchy rule is stale"):
        build(biz=rows)


def test_counties_split_from_cities_with_sf():
    doc = build()
    assert len(doc["counties"]) == 58  # 57 county rows + San Francisco city-county
    assert any(c["county"] == "San Francisco" for c in doc["counties"])
    assert all(not c["city"].upper().endswith(" COUNTY") for c in doc["cities"])


def test_suppressed_city_is_null_and_counted():
    doc = build()
    tiny = next(c for c in doc["cities"] if c["city"] == "Tinyville")
    assert tiny["taxable_sales_usd"] is None
    assert tiny["suppressed"] is True
    assert doc["suppressed_city_count"] == 1


def test_fund_split_uses_latest_complete_fy():
    doc = build()
    # FY2025 has a placeholder 0 for the GF; FY2024 is the latest complete year
    assert doc["fund_split_fiscal_year"] == "2024-25"
    assert doc["budget_reference"]["stats_total_usd"] == 100
    gf = next(f for f in doc["fund_split"] if f["fund"] == "State General Fund")
    assert gf["revenue_usd"] == 100

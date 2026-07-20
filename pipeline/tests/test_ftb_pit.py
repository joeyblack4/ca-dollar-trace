"""ftb_pit builder tests: band condensation, suppression accounting, fail-honest gates."""

import pytest

from cadollar.ingest.csv_download import QualityGateError
from cadollar.ingest.ftb_pit import COMPOSITION_COLS, OVERLAY_COLS, build_pit_docs

CA_COUNTIES = [f"County {i:02d}" for i in range(58)]


def _b4a_row(year, agic, returns, agi, tax, **extra):
    row = {
        "Taxable Year": str(year),
        "AGIC": agic,
        "All Returns": f"{returns:,}",
        "California AGI": f"{agi:,}",
        "Total Tax Liability": f"{tax:,}",
        "Total Income": extra.pop("total_income", "0"),
        "Mental Health Tax": "0",
    }
    for _, gain_col, gain_returns_col, loss_col in COMPOSITION_COLS:
        row[gain_col] = "0"
        row[gain_returns_col] = "0"
        if loss_col:
            row[loss_col] = "0"
    for _, col in OVERLAY_COLS:
        row[col] = "0"
    row.update(extra)
    return row


def _b4a():
    return [
        _b4a_row(2022, "Negative", 100, -5_000, 0),
        _b4a_row(2022, "Zero", 50, 0, 0),
        _b4a_row(2022, "1  to  999", 10, 5_000, 1_000),
        _b4a_row(2022, "5,000  to  5,999", 20, 110_000, 2_000),
        _b4a_row(2022, "40,000  to  49,999", 40, 1_800_000, 40_000_000),
        _b4a_row(2022, "100,000  to  149,999", 30, 3_600_000, 50_000_000),
        _b4a_row(2022, "1,000,000  to  1,999,999", 5, 7_000_000, 20_000_000),
        _b4a_row(2022, "10,000,000  and  over", 2, 30_000_000, 30_000_000),
        # prior year must be ignored
        _b4a_row(2021, "Negative", 999, -1, 999_999_999),
    ]


TOTAL_TAX = 1_000 + 2_000 + 40_000_000 + 50_000_000 + 20_000_000 + 30_000_000


def _b3(total=TOTAL_TAX):
    return [
        {"Taxable Year": "2022", "Total Tax Liability": f"{total:,}"},
        {"Taxable Year": "2021", "Total Tax Liability": "1"},
    ]


def _b7_row(year, agic, county, returns, agi, tax):
    return {
        "Taxable Year": str(year),
        "AGIC": agic,
        "County": county,
        "All Returns": "" if returns is None else str(returns),
        "Adjusted Gross Income": "" if agi is None else str(agi),
        "Tax Assessed": "" if tax is None else str(tax),
    }


def _b7():
    rows = []
    for county in CA_COUNTIES:
        rows.append(_b7_row(2022, "Zero and Deficit", county, 10, -100, 0))
        rows.append(_b7_row(2022, "100,000 and over", county, 20, 4_000, 1_000_000))
    # suppressed cell in one county
    rows.append(_b7_row(2022, "1,000,000 and over", CA_COUNTIES[0], None, None, None))
    rows.append(_b7_row(2022, "100,000 and over", "Nonresident", 7, 900, 500_000))
    total = 58 * 1_000_000 + 500_000
    rows.append(_b7_row(2022, "all", "State Totals", 58 * 30 + 7, 0, total))
    return rows


def _zips():
    rows = []
    for county in CA_COUNTIES[:55]:
        rows.append(
            {
                "TaxYear": "2023",
                "ZipCode": "90001",
                "State": "CA",
                "City": "Somewhere",
                "County": county,
                "Returns": "100",
                "CAAGI": "5000000",
                "TotalTaxLiability": "250000",
            }
        )
    # non-CA row must be excluded
    rows.append(
        {
            "TaxYear": "2023",
            "ZipCode": "89000",
            "State": "NV",
            "City": "Reno",
            "County": "Washoe",
            "Returns": "5",
            "CAAGI": "1",
            "TotalTaxLiability": "1",
        }
    )
    return rows


def _waterfall(pit_usd=TOTAL_TAX):
    return {
        "budget_year": "2025-26",
        "general_fund": {"revenue": [{"name": "Personal Income Tax", "usd": pit_usd}]},
    }


def build(**overrides):
    kwargs = dict(b4a=_b4a(), b3=_b3(), b7=_b7(), zips=_zips(), waterfall=_waterfall(), min_rows=1)
    kwargs.update(overrides)
    return build_pit_docs(**kwargs)


def test_bands_condense_and_shares_sum():
    doc, _ = build()
    assert doc["tax_year"] == 2022
    by_label = {b["label"]: b for b in doc["brackets"]}
    # $1–999 and $5,000–5,999 classes merge into the first band
    assert by_label["$1 – $9,999"]["returns"] == 30
    assert by_label["$1 – $9,999"]["tax_liability_usd"] == 3_000
    assert by_label["Negative or zero AGI"]["returns"] == 150
    assert doc["statewide"]["tax_liability_usd"] == TOTAL_TAX
    # cumulative share from the top: the top band alone
    assert by_label["$10 million and over"]["cum_share_of_tax_pct"] == pytest.approx(
        30_000_000 / TOTAL_TAX * 100, abs=0.01
    )
    # bottom band's cumulative covers everything
    assert by_label["Negative or zero AGI"]["cum_share_of_tax_pct"] == 100.0
    assert sum(b["share_of_tax_pct"] for b in doc["brackets"]) == pytest.approx(100, abs=0.1)


def test_high_income_tiers_from_top_classes():
    doc, _ = build()
    assert [t["floor_usd"] for t in doc["high_income"]] == [1_000_000, 10_000_000]
    assert doc["high_income"][1]["share_of_tax_pct"] == pytest.approx(
        30_000_000 / TOTAL_TAX * 100, abs=0.01
    )


def test_b3_drift_refuses_to_publish():
    with pytest.raises(QualityGateError, match="parsing drift"):
        build(b3=_b3(total=TOTAL_TAX * 2))


def test_counties_suppression_counted_not_imputed():
    doc, _ = build()
    assert len(doc["counties"]) == 58
    c0 = next(c for c in doc["counties"] if c["county"] == CA_COUNTIES[0])
    assert c0["suppressed_cells"] == 1
    suppressed = [b for b in c0["brackets"] if b["returns"] is None]
    assert len(suppressed) == 1  # published as null, never zero
    assert doc["non_geographic"][0]["label"] == "Nonresident"
    assert doc["county_cross_check"]["suppression_residual_usd"] == 0


def test_missing_county_refuses_to_publish():
    b7 = [r for r in _b7() if r["County"] != CA_COUNTIES[0]]
    with pytest.raises(QualityGateError, match="expected 58"):
        build(b7=b7)


def test_waterfall_sanity_band_trips_on_units_error():
    with pytest.raises(QualityGateError, match="sanity band"):
        build(waterfall=_waterfall(pit_usd=TOTAL_TAX * 1000))


def test_zip_docs_grouped_by_county_ca_only():
    doc, zip_docs = build()
    assert doc["zip_tax_year"] == 2023
    assert len(zip_docs) == 55
    assert doc["zip_coverage"]["zips"] == 55
    slug = sorted(zip_docs)[0]
    assert zip_docs[slug]["zips"][0]["tax_liability_usd"] == 250_000
    # the NV row must not appear anywhere
    assert all("Washoe" not in d["county"] for d in zip_docs.values())


def test_composition_nets_mixed_sign_losses_and_overlays():
    b4a = _b4a()
    # top class: wages 100, cap gains 500 with a NEGATIVE-sign loss cell of -50,
    # partnerships 300 with a POSITIVE-sign loss cell of 100 (source is inconsistent)
    b4a[-2] = _b4a_row(
        2022,
        "10,000,000  and  over",
        2,
        30_000_000,
        30_000_000,
        total_income="750",
        **{
            "Wages And Salaries": "100",
            "Returns With Wages and Salaries": "2",
            "Net Sale Of Capital Assets Profit": "500",
            "Returns With Net Sale Of Capital Assets Profit": "2",
            "Net Sale Of Capital Assets Loss": "-50",
            "Partnerships and S-Corp Gain": "300",
            "Returns With Partnerships and S-Corp Gain": "1",
            "Partnerships and S-Corp Loss": "100",
            "Returns With Senior Or Blind Exemption Credit": "1",
            "Returns With Mental Health Tax": "2",
        },
    )
    b4a[-2]["Mental Health Tax"] = "9,000"
    doc, _ = build(b4a=b4a)
    top = doc["display_bands"][-1]
    comp = {c["source"]: c for c in top["composition"]}
    assert comp["Capital gains"]["usd"] == 450  # 500 - |−50|
    assert comp["Partnerships & S-corps"]["usd"] == 200  # 300 - |100|
    assert comp["Wages & salaries"]["usd"] == 100
    assert top["itemized_income_usd"] == 750
    assert top["total_income_usd"] == 750
    # sorted descending, shares of itemized total
    assert top["composition"][0]["source"] == "Capital gains"
    assert top["composition"][0]["share_of_income_pct"] == 60.0
    assert top["overlays"]["seniors"] == 1
    assert top["overlays"]["mental_health_tax"] == 2
    assert top["overlays"]["mental_health_tax_usd"] == 9_000


def test_overlay_count_exceeding_returns_refuses_to_publish():
    b4a = _b4a()
    b4a[-2] = _b4a_row(
        2022,
        "10,000,000  and  over",
        2,
        30_000_000,
        30_000_000,
        **{"Returns With Renter's Credit": "5"},  # 5 claims from 2 returns
    )
    with pytest.raises(QualityGateError, match="exceeds"):
        build(b4a=b4a)


def test_itemized_drift_refuses_to_publish():
    b4a = _b4a()
    b4a[-2] = _b4a_row(
        2022,
        "10,000,000  and  over",
        2,
        30_000_000,
        30_000_000,
        total_income="1,000",
        **{"Wages And Salaries": "100"},  # itemizes to 100 vs Total Income 1000
    )
    with pytest.raises(QualityGateError, match="stale column map"):
        build(b4a=b4a)


def test_budget_reference_records_both_numbers():
    doc, _ = build()
    ref = doc["budget_reference"]
    assert ref["budget_year"] == "2025-26"
    assert ref["waterfall_usd"] == TOTAL_TAX
    assert ref["stats_total_usd"] == TOTAL_TAX
    assert "different years" in ref["note"]

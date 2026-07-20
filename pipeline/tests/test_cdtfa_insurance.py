"""cdtfa_insurance builder tests: leaf reconciliation and shape-change gates."""

import pytest

from cadollar.ingest.cdtfa_insurance import build_insurance_doc
from cadollar.ingest.csv_download import QualityGateError


def _row(year, typ, n, amount):
    return {
        "AssessmentYear": year,
        "BusinessYear": year - 1,
        "TypeOfInsurer": typ,
        "NumberOfBusinesses": n,
        "AssessedAmount": amount,
    }


def _rows():
    return [
        _row(2025, "Fire and Casualty", 1000, 2_500),
        _row(2025, "Life", 500, 1_000),
        _row(2025, "Ocean Marine", 600, 100),
        _row(2025, "Title", 33, 400),
        _row(2025, "Adjustments Net adjustments", 276, -50),
        _row(2025, "Totals", 2133, 4_000),
        _row(2025, "Grand Totals", 2409, 3_950),
        # older year must be ignored
        _row(2024, "Fire and Casualty", 900, 999_999),
    ]


def _waterfall(usd=4_000):
    return {
        "budget_year": "2025-26",
        "general_fund": {"revenue": [{"name": "Insurance Tax", "usd": usd}]},
    }


def test_leaf_types_reconcile_and_adjustments_visible():
    doc = build_insurance_doc(_rows(), _waterfall())
    assert doc["assessment_year"] == 2025
    assert [t["type"] for t in doc["types"]][0] == "Fire and Casualty"
    assert doc["reconciliation"] == {
        "leaf_sum_usd": 4_000,
        "totals_usd": 4_000,
        "grand_totals_usd": 3_950,
    }
    assert doc["net_adjustments_usd"] == -50


def test_shape_change_refuses_to_publish():
    rows = [r for r in _rows() if r["TypeOfInsurer"] != "Life"]
    with pytest.raises(QualityGateError, match="missing"):
        build_insurance_doc(rows, _waterfall())


def test_sanity_band():
    with pytest.raises(QualityGateError, match="sanity band"):
        build_insurance_doc(_rows(), _waterfall(usd=4_000_000))

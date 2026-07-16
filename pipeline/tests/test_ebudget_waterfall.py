"""Waterfall builder tests: unit normalization + fail-honest cross-total gates."""

import pytest

from cadollar.config import Settings
from cadollar.ingest.csv_download import QualityGateError
from cadollar.ingest.ebudget import build_waterfall


def _sankey(rev=(("Personal Income Tax", 100), ("Sales and Use Tax", 50)),
            exp=(("Health and Human Services", 90), ("K-12 Education", 70))):
    nodes = [{"node": 0, "name": ""}]
    links = []
    for i, (name, v) in enumerate(rev, start=1):
        nodes.append({"node": i, "name": name})
        links.append({"source": i, "target": 0, "value": v})
    for j, (name, v) in enumerate(exp, start=len(rev) + 1):
        nodes.append({"node": j, "name": name})
        links.append({"source": 0, "target": j, "value": v})
    return {
        "nodes": nodes,
        "links": links,
        "revenueTotal": sum(v for _, v in rev),
        "expenditureTotal": sum(v for _, v in exp),
    }


def _stats():
    return [
        {"orgCd": "4000", "legalTitl": "Health and Human Services", "stateBudgetYearDols": 700,
         "allBudgetYearDols": 1000, "generalFundTotal": 500, "specialFundTotal": 200,
         "bondFundTotal": 0, "budgetYearPers": 10.0, "stateGrandTotal": 1000,
         "displayOnWebFlg": "Y"},
        {"orgCd": "6010", "legalTitl": "K thru 12 Education", "stateBudgetYearDols": 300,
         "allBudgetYearDols": 400, "generalFundTotal": 300, "specialFundTotal": 0,
         "bondFundTotal": 0, "budgetYearPers": 5.0, "stateGrandTotal": 1000,
         "displayOnWebFlg": "Y"},
    ]


@pytest.fixture
def settings():
    return Settings(storage_mode="local")


def test_units_normalized_and_gap_computed(settings):
    doc = build_waterfall(_sankey(), _stats(), settings)
    gf = doc["general_fund"]
    assert gf["revenue_total_usd"] == 150 * 1_000_000  # $M -> $
    assert gf["gap_usd"] == (160 - 150) * 1_000_000
    assert doc["state_grand_total_usd"] == 1000 * 1_000  # $K -> $
    assert doc["agencies"][0]["title"] == "Health and Human Services"
    # curated downstream annotations attach
    hhs = next(d for d in doc["downstream_visibility"] if d["node"] == "Health and Human Services")
    assert any(h["flag"] == "trail_ends_here" for h in hhs["hops"])


def test_mismatched_totals_refuse_to_publish(settings):
    bad = _sankey()
    bad["revenueTotal"] += 1
    with pytest.raises(QualityGateError):
        build_waterfall(bad, _stats(), settings)


def test_agency_sum_gate(settings):
    stats = _stats()
    stats[0]["stateBudgetYearDols"] = 100  # sum 400 vs grand total 1000
    with pytest.raises(QualityGateError):
        build_waterfall(_sankey(), stats, settings)

"""Contract tests over the COMMITTED published data (site/public/data).

These run in CI on every push: any commit that changes the published JSON must
keep every invariant the site's rendering relies on. This is the data-shape
firewall between pipeline and site — if a connector starts emitting something
the UI would mis-render, the build goes red before the site does.
"""

import json
from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parents[2] / "site" / "public" / "data"

ENVELOPE_FIELDS = ("source", "as_of", "ingested_at", "cadence", "coverage_flag", "caveats", "data")
SOURCE_FIELDS = ("name", "publisher", "url", "license")
COVERAGE_FLAGS = {"traceable", "category_only", "trail_ends_here", "masked"}


def published_files() -> list[Path]:
    return sorted(DATA.rglob("*.json"))


def load(name: str) -> dict:
    return json.loads((DATA / name).read_text())


# ---------- universal envelope contract ----------


@pytest.mark.parametrize("path", published_files(), ids=lambda p: str(p.relative_to(DATA)))
def test_envelope_complete(path: Path):
    doc = json.loads(path.read_text())
    for field in ENVELOPE_FIELDS:
        assert field in doc, f"envelope missing {field}"
    for field in SOURCE_FIELDS:
        assert doc["source"].get(field), f"source block missing {field}"
    assert doc["coverage_flag"] in COVERAGE_FLAGS
    assert isinstance(doc["caveats"], list) and doc["caveats"], "every source must carry caveats"
    assert doc["as_of"], "as_of stamp required"


# ---------- budget waterfall ----------


def test_waterfall_sums():
    gf = load("budget_waterfall.json")["data"]["general_fund"]
    assert abs(sum(r["usd"] for r in gf["revenue"]) - gf["revenue_total_usd"]) <= 1
    assert abs(sum(e["usd"] for e in gf["expenditure"]) - gf["expenditure_total_usd"]) <= 1
    assert gf["gap_usd"] == gf["expenditure_total_usd"] - gf["revenue_total_usd"]


def test_waterfall_agencies_reconcile():
    d = load("budget_waterfall.json")["data"]
    total = sum(a["state_funds_usd"] for a in d["agencies"])
    total += d.get("agencies_excluded_from_display", {}).get("state_funds_usd", 0)
    assert abs(total - d["state_grand_total_usd"]) <= 0.005 * d["state_grand_total_usd"]


def test_waterfall_lists_sorted_desc():
    # the Sankey/drill use [0] as the max bar — order is a rendering contract
    d = load("budget_waterfall.json")["data"]
    for key in ("revenue", "expenditure"):
        vals = [r["usd"] for r in d["general_fund"][key]]
        assert vals == sorted(vals, reverse=True), f"general_fund.{key} not sorted desc"


# ---------- agencies ----------


def agency_codes() -> list[str]:
    return [a["org_cd"] for a in load("budget_waterfall.json")["data"]["agencies"]]


@pytest.mark.parametrize("cd", agency_codes())
def test_agency_detail_contract(cd: str):
    ag = load(f"agencies/{cd}.json")["data"]
    assert ag["summary_cross_check"]["drift_pct"] <= 0.5
    assert ag["departments"], "agency must list departments"
    totals = [d["total_usd"] for d in ag["departments"]]
    assert totals == sorted(totals, reverse=True), "departments not sorted desc"
    for dept in ag["departments"]:
        integ = dept["integrity"]
        assert (
            "matches_department_total" in integ or "no_program_detail_published" in integ
        ), f"{dept['org_cd']}: integrity block missing"
        if dept["programs"]:
            pvals = [p["usd"] for p in dept["programs"]]
            assert pvals == sorted(pvals, reverse=True), f"{dept['org_cd']} programs unsorted"


def test_agency_integrity_flag_budget():
    """Genuine lines!=total mismatches are allowed but must stay rare."""
    flagged = 0
    for cd in agency_codes():
        for dept in load(f"agencies/{cd}.json")["data"]["departments"]:
            if dept["integrity"].get("matches_department_total") is False:
                flagged += 1
    assert flagged <= 6, (
        f"{flagged} departments fail lines-vs-total — investigate before adding sources"
    )


# ---------- checkbook vendors ----------


def vendor_files() -> list[Path]:
    return sorted(DATA.glob("vendors/*.json"))


@pytest.mark.parametrize("path", vendor_files(), ids=lambda p: p.stem)
def test_vendor_dept_contract(path: Path):
    for d in json.loads(path.read_text())["data"]["departments"]:
        assert d["confidential_usd"] <= d["vendor_total_usd"] + 1 or d["vendor_total_usd"] <= 0
        assert d["public_sector_usd"] <= d["vendor_total_usd"] + 1 or d["vendor_total_usd"] <= 0
        assert "sco_interface_net_usd" in d, "SCO interface disclosure required"
        assert "amount_unparsed_count" in d, "unparsed-count disclosure required"
        assert d["top_vendors_limit"] == 25
        cov = d["checkbook_coverage_pct"]
        if cov is not None:
            assert -5 <= cov <= 500, f"{d['org_cd']}: coverage {cov}% implausible"
        vals = [v["usd"] for v in d["top_vendors"]]
        assert vals == sorted(vals, reverse=True), f"{d['org_cd']} top_vendors unsorted"
        for v in d["top_vendors"]:
            if v["gross_usd"] is not None:
                assert v["gross_usd"] >= v["usd"], "gross must be >= net"
        # fiscal year label shape: "2025-26"
        assert len(d["fiscal_year"].split("-")) == 2


def test_vendor_profiles_contract():
    vp = load("vendor_profiles.json")["data"]["vendors"]
    assert 400 <= len(vp) <= 500
    for name, p in vp.items():
        year_sum = sum(p["years"].values())
        assert abs(year_sum - p["total_usd"]) <= max(1, 0.001 * abs(p["total_usd"])), name
        dept_sum = sum(d["usd"] for d in p["departments"])
        assert abs(dept_sum - p["total_usd"]) <= max(1, 0.001 * abs(p["total_usd"])), name
        for fy, gross in (p.get("years_gross") or {}).items():
            assert gross >= p["years"][fy], f"{name} {fy}: gross < net"


# ---------- grants ----------


def test_grants_awards_contract():
    d = load("grants_awards.json")["data"]
    assert d["by_agency_limit"] == 40
    assert d["agency_count_total"] >= len(d["by_agency"])
    assert d["agencies_not_shown_usd"] >= 0
    for fy in d["by_fiscal_year"]:
        assert "subrecipient_flag_unknown_count" in fy
        known = fy["awarded_known_usd"] or 0
        subs = fy["with_subrecipients_usd"] or 0
        assert subs <= known + 1


def test_grants_summary_unknowns_disclosed():
    d = load("grants_summary.json")["data"]
    for row in d["totals_by_status"]:
        assert "funds_unknown_count" in row


# ---------- bhcip ----------


def test_bhcip_contract():
    d = load("bhcip_awards.json")["data"]
    rows = [(e["name"], p["project"], p["round"]) for e in d["entities"] for p in e["projects"]]
    assert len(rows) == d["project_count"]
    assert len(set(rows)) == len(rows), "duplicate entity+project+round rows"
    assert len(d["entities"]) == d["entity_count"]
    counts = [e["project_count"] for e in d["entities"]]
    assert counts == sorted(counts, reverse=True)


# ---------- medi-cal managed care plans ----------


def test_medical_plans_contract():
    d = load("medical_plans.json")["data"]
    assert d["total_enrollees"] > 10_000_000, "Medi-Cal managed care should be ~14M people"
    assert d["plan_count"] >= 100
    assert d["capitation_files_skipped"] == [], "a capitation model file failed to parse"
    assert d["enrollee_weighted_match_pct"] is not None
    assert d["enrollee_weighted_match_pct"] >= 85, "rate-name match rate collapsed"
    enrollees = [p["enrollees"] or 0 for p in d["plans"]]
    assert enrollees == sorted(enrollees, reverse=True), "plans not sorted by enrollment"
    assert abs(sum(enrollees) - d["total_enrollees"]) <= 1
    for p in d["plans"]:
        cap = p["capitation"]
        if cap:
            lo, hi = cap["pmpm_range"]
            assert 0 < lo <= hi < 50_000, f"{p['plan_name']}: implausible PMPM {lo}-{hi}"
            assert cap["name_match"] in {"exact", "alias", "prefix"}


# ---------- federal ----------


def test_federal_contract():
    d = load("federal_ca.json")["data"]
    masked = [r for r in d["recipients"] if r["masked_aggregate"]]
    named = [r for r in d["recipients"] if not r["masked_aggregate"]]
    assert masked, "the privacy-masked aggregate must be present, not dropped"
    assert all(r["coverage_flag"] == "masked" for r in masked)
    assert named and all(r["uei"] for r in named[:10])


# ---------- county finances ----------


def test_county_finances_contract():
    d = load("county_finances.json")["data"]
    assert d["county_count"] == 57, "57 counties expected (SF files as a city)"
    assert d["not_in_this_dataset"], "SF exclusion must be disclosed"
    assert d["total_latest_usd"] > 50e9
    totals = [c["total_usd"] or 0 for c in d["counties"]]
    assert totals == sorted(totals, reverse=True), "counties not sorted desc"
    for c in d["counties"]:
        assert "amount_unparsed_count" in c
        assert c["top_categories"], f"{c['county']}: no categories"
        if c["per_capita_usd"] is not None:
            assert 500 <= c["per_capita_usd"] <= 30000, f"{c['county']}: implausible per-capita"

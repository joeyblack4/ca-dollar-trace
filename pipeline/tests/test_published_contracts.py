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


def _local_entities_contract(d: dict):
    """Shared invariants for the SCO county/city expenditure documents."""
    totals = [c["total_usd"] or 0 for c in d["counties"]]
    assert totals == sorted(totals, reverse=True), "entities not sorted desc"
    assert "per_capita_withheld" in d, "per-capita screening disclosure required"
    for c in d["counties"]:
        assert "amount_unparsed_count" in c
        assert c["top_categories"], f"{c['county']}: no categories"
        if c["per_capita_usd"] is not None:
            # the pipeline withholds per-capita outside these bounds
            assert 200 <= c["per_capita_usd"] <= 30000, f"{c['county']}: implausible per-capita"
        else:
            pass  # withheld (no population, or flagged implausible)


def test_county_finances_contract():
    d = load("county_finances.json")["data"]
    assert d["county_count"] == 57, "57 counties expected (SF files as a city)"
    assert d["not_in_this_dataset"], "SF exclusion must be disclosed"
    assert d["entities_not_shown"] == 0, "all 57 counties must publish detail"
    assert d["total_latest_usd"] > 50e9
    _local_entities_contract(d)


def test_city_finances_contract():
    d = load("city_finances.json")["data"]
    assert d["county_count"] >= 400, "there are ~480 CA cities"
    assert d["entities_published"] == 50
    assert d["entities_not_shown"] == d["county_count"] - 50
    assert d["entities_not_shown_total_usd"] > 0, "remainder aggregate must be disclosed"
    sf = next((c for c in d["counties"] if c["county"] == "San Francisco"), None)
    assert sf is not None, "San Francisco must be present (closes the 58th-county gap)"
    assert (sf["total_usd"] or 0) > 5e9
    _local_entities_contract(d)


# ---------- k-12 school districts ----------


def test_k12_finances_contract():
    d = load("k12_finances.json")["data"]
    # ~1,250 LEAs report their own books (many charters report through their
    # authorizing district); the raw rollup has ~2,000 files
    assert d["lea_count"] >= 1100, "LEA count collapsed"
    assert 90e9 < d["statewide_spend_usd"] < 140e9, "GF operating spend out of plausible range"
    assert d["next_year_budget_rows_excluded"] > 100_000, "budget-section exclusion disclosure"
    assert d["district_names_unmatched"] <= d["lea_count"] * 0.1, "too many unnamed districts"
    assert d["districts_not_shown_spend_usd"] >= 0
    labels = {c["object_class"] for c in d["statewide_by_class"]}
    assert "Teacher salaries" in labels and "Services & operating (outside providers)" in labels
    spends = [x["spend_usd"] or 0 for x in d["districts"]]
    assert spends == sorted(spends, reverse=True), "districts not sorted desc"
    la = next(
        (x for x in d["districts"] if x["district"] and "Los Angeles Unified" in x["district"]),
        None,
    )
    assert la is not None, "LAUSD must be present and named"
    assert (la["spend_usd"] or 0) > 5e9


# ---------- city checkbooks (LA + SF) ----------


def test_city_checkbooks_contract():
    d = load("city_checkbooks.json")["data"]
    la, sf = d["los_angeles"], d["san_francisco"]
    assert la["measure"] != sf["measure"], "the two measures must stay labeled apart"
    assert la["total_usd"] > 5e9 and la["transaction_count"] > 100_000
    assert sf["total_usd"] > 10e9 and sf["contract_count"] > 10_000
    for city in (la, sf):
        vals = [v["usd"] for v in city["top_vendors"]]
        assert vals == sorted(vals, reverse=True)
        assert city["by_department"], "department breakdown required"


# ---------- federal audits (FAC) ----------


def test_federal_audits_contract():
    d = load("federal_audits.json")["data"]
    assert d["entity_count"] > 3000
    assert d["total_federal_expended_usd"] > 150e9, "complete years include the State's audit"
    top = d["top_auditees"][0]
    assert top["name"] == "State of California", "a complete year is headlined by the State"
    vals = [a["federal_expended_usd"] for a in d["top_auditees"]]
    assert vals == sorted(vals, reverse=True)
    assert d["top_auditees_limit"] == 60
    types = {t["entity_type"] for t in d["by_entity_type"]}
    assert {"state", "local", "non-profit", "higher-ed"} <= types


# ---------- nonprofit enrichment ----------


def test_nonprofits_contract():
    d = load("nonprofits.json")["data"]
    assert d["registry_org_count"] > 200_000
    assert d["matched"] >= 100
    assert d["with_990"] > 0
    for name, org in d["organizations"].items():
        assert org["registry_status"], name
        assert "may_operate" in org, name
        n990 = org.get("irs_990")
        if n990:
            assert n990["propublica_url"].startswith("https://projects.propublica.org/")
    # public agencies must never appear in a charity-compliance list
    for name in d["not_in_good_standing"]:
        assert "COUNTY" not in name.upper() or "OF" in name.upper().split()[0:1], name


# ---------- special districts ----------


def test_district_finances_contract():
    d = load("district_finances.json")["data"]
    assert d["county_count"] > 3000, "~4,800 special districts expected"
    assert d["entities_published"] == 60
    assert d["total_latest_usd"] > 50e9
    assert d["entities_not_shown_total_usd"] > 0
    _local_entities_contract(d)


# ---------- federal subawards ----------


def test_federal_subawards_contract():
    d = load("federal_subawards.json")["data"]
    assert d["edges_shown"] >= 200
    assert "note" in d, "top-N scope must be disclosed"
    vals = [e["usd"] for e in d["largest_edges"]]
    assert vals == sorted(vals, reverse=True)
    for e in d["largest_edges"]:
        assert e["prime"] and e["sub"] and e["usd"] > 0
        assert e["kind"] in {"grant", "contract"}


# ---------- government compensation ----------


def test_compensation_contract():
    d = load("compensation.json")["data"]
    assert d["statewide_wages_usd"] > 70e9, "state+county+city wages should exceed $70B"
    assert d["statewide_benefits_usd"] > 20e9
    for lv in ("state", "county", "city"):
        x = d["levels"][lv]
        assert x["positions"] > 100_000, f"{lv}: too few positions"
        assert x["wages_usd"] > 10e9
        tw = [e["wages_usd"] + e["benefits_usd"] for e in x["top_employers"]]
        assert tw == sorted(tw, reverse=True), f"{lv} top_employers unsorted"
    # county names must resolve for the /local payroll column
    assert "LOS ANGELES" in d["by_employer"]

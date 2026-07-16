"""Unit tests for connector transforms on synthetic fixtures — no network."""

import json
from datetime import UTC, datetime

import pytest

from cadollar.cli import HEAVY, RUN_ORDER, RUNNERS
from cadollar.config import Settings
from cadollar.ingest.bhcip import run_bhcip
from cadollar.ingest.ebudget_detail import build_agency_details
from cadollar.ingest.fiscal_vendor import _fy, _ingest_file, publish_vendor_summaries
from cadollar.sources import load_source
from cadollar.storage import LocalStorage, read_manifest


def test_run_order_covers_all_runners():
    assert set(RUN_ORDER) == set(RUNNERS)
    assert RUN_ORDER.index("ebudget_enacted") < RUN_ORDER.index("ebudget_detail")
    assert HEAVY <= set(RUN_ORDER)


# ---------- ebudget_detail.build_agency_details ----------


def _member(org, total, gf=0, programs=None, cap=None):
    return {
        "stats": {
            "orgCd": org,
            "legalTitl": f"Dept {org}",
            "allBudgetYearDols": total,
            "generalFundTotal": gf,
            "budgetYearPers": 1.0,
        },
        "programs": {
            "totals": [],
            "lines": [
                {"programCode": c, "programTitl": t, "byDols": v, "byPersYrs": None}
                for c, t, v in (programs or [])
            ],
        }
        if programs is not None
        else None,
        "funds": [{"fundClassCd": "G", "byTotDols": total}],
        "cap_outlay": [{"fundClassCd": "S", "byTotDols": cap}] if cap else None,
    }


def _summary(cd, total):
    return {"org_cd": cd, "title": f"Agency {cd}", "all_funds_usd": total * 1000}


def test_capital_outlay_closes_integrity_gap():
    # realistic magnitudes ($K units): $800M total = $115M programs + $685M cap outlay
    members = [_member("111", 800_000, programs=[("p1", "Prog", 115_000)], cap=685_000)]
    out = build_agency_details({"9000": members}, [_summary("9000", 800_000)])
    dept = out["9000"]["departments"][0]
    assert dept["integrity"]["matches_department_total"] is True
    assert any("Capital outlay" in p["title"] for p in dept["programs"])


def test_genuine_mismatch_stays_flagged():
    # gap ($2.5B vs $5B) far above the $1M/0.1% integrity floor
    members = [_member("222", 5_000_000, programs=[("p1", "Prog", 2_500_000)])]
    out = build_agency_details({"9000": members}, [_summary("9000", 5_000_000)])
    assert out["9000"]["departments"][0]["integrity"]["matches_department_total"] is False


def test_missing_program_detail_flagged_not_zeroed():
    members = [_member("333", 100_000, programs=None)]
    out = build_agency_details({"9000": members}, [_summary("9000", 100_000)])
    dept = out["9000"]["departments"][0]
    assert dept["integrity"] == {"no_program_detail_published": True}
    assert dept["total_usd"] == 100_000_000


def test_agency_drift_gate_aborts():
    from cadollar.ingest.csv_download import QualityGateError

    members = [_member("444", 50_000)]
    with pytest.raises(QualityGateError):
        build_agency_details({"9000": members}, [_summary("9000", 100_000)])


# ---------- fiscal_vendor end-to-end on synthetic files ----------

CSV_HEADER = (
    "business_unit,agency_name,department_name,document_id,related_document,accounting_date,"
    "fiscal_year_begin,accounting_period,VENDOR_NAME,account,account_type,account_category,"
    "account_sub_category,account_description,fund_code,fund_group,fund_description,"
    "program_code,program_description,sub_program_description,budget_reference,"
    "budget_reference_category,budget_reference_sub_category,budget_reference_description,"
    "year_of_enactment,monetary_amount"
)


def _txn(bu, fy, vendor, amount, account="Consulting"):
    return (
        f'"{bu}","Agency","Dept {bu}","{bu}.1","","{fy}-10-01","{fy}","4","{vendor}",'
        f'"5340580","Operating","Cat","Sub","{account}","0001","General Fund","General Fund",'
        f'"1000000","Program X","","001","Ref","Sub","Desc","{fy}","{amount}"'
    )


@pytest.fixture
def vendor_env(tmp_path, monkeypatch):
    settings = Settings(storage_mode="local", data_dir=tmp_path)
    storage = LocalStorage(tmp_path)
    cfg = load_source(settings, "fiscal_vendor")
    bodies = {}
    monkeypatch.setattr(
        "cadollar.ingest.fiscal_vendor.fetch_bytes",
        lambda url, **kw: bodies[url],
    )
    return settings, storage, cfg, bodies


def test_fiscal_vendor_aggregation_and_flags(vendor_env, tmp_path):
    settings, storage, cfg, bodies = vendor_env
    now = datetime.now(UTC)
    # dept 1234: real vendor + public-sector payee + confidential + unparseable
    rows = [
        _txn("1234", "2024", "ACME WIDGETS INC", "1000.00"),
        _txn("1234", "2024", "DEPARTMENT OF TECHNOLOGY", "500.00"),
        _txn("1234", "2024", "CONFIDENTIAL", "200.00"),
        _txn("1234", "2024", "ACME WIDGETS INC", "not-a-number"),
        # adjustment pair: recorded then mostly reversed
        _txn("1234", "2024", "REVERSED LLC", "1000.00"),
        _txn("1234", "2024", "REVERSED LLC", "-900.00", account="SCO Inbound Interface Dept Exp"),
    ]
    body = ("﻿" + CSV_HEADER + "\n" + "\n".join(rows) + "\n").encode()
    url = "https://example.com/Vendor_1234_TestDept_FY24.csv"
    bodies[url] = body
    state = _ingest_file(
        storage,
        cfg,
        {"FileName": "Vendor_1234_TestDept_FY24.csv", "UploadDate": "2026-01-01",
         "FileSize": "1 KB", "Download": url},
        now,
    )
    assert state["rows"] == 6

    key = publish_vendor_summaries(
        storage, cfg, settings, {"Vendor_1234_TestDept_FY24.csv": state}, now
    )
    doc = json.loads(storage.get_bytes(key))
    dept = None
    for f in (tmp_path / "published" / "vendors").glob("*.json"):
        for d in json.loads(f.read_bytes())["data"]["departments"]:
            if d["org_cd"] == "1234":
                dept = d
    # dept won't match a budget agency -> lands in unmatched (overview)
    if dept is None:
        unmatched = doc["data"]["unmatched_business_units"]
        assert any(u["org_cd"] == "1234" for u in unmatched)
        # totals: 1000 + 500 + 200 + (1000-900) = 1800
        row = next(u for u in unmatched if u["org_cd"] == "1234")
        assert abs(row["vendor_total_usd"] - 1800) < 0.01
    assert doc["data"]["amount_unparsed_total"] == 1


def test_fy_parse():
    assert _fy("Vendor_1234_X_FY24.csv") == 24
    assert _fy("nonsense.csv") is None


# ---------- bhcip on fixture snapshot ----------


def test_bhcip_parses_snapshot(tmp_path, monkeypatch):
    settings = Settings(storage_mode="local", data_dir=tmp_path)
    storage = LocalStorage(tmp_path)
    cfg = load_source(settings, "bhcip_awards").model_copy(update={"min_rows": 2})
    src_dir = tmp_path / "sources" / "curated"
    src_dir.mkdir(parents=True)
    (src_dir / "bhcip_awardees_snapshot.csv").write_text(
        "entity_name,project_name,funding_round\n"
        "Org A,Project 1,Round 1\n"
        "Org A,Project 2,Round 2\n"
        "Org B,Project 3,Round 1\n",
        encoding="utf-8-sig",  # BOM must not break the header
    )
    settings = Settings(storage_mode="local", data_dir=tmp_path, sources_dir=tmp_path / "sources")
    key = run_bhcip(storage, cfg, settings)
    doc = json.loads(storage.get_bytes(key))["data"]
    assert doc["project_count"] == 3
    assert doc["entity_count"] == 2
    assert doc["entities"][0]["name"] == "Org A"  # sorted by project count
    m = read_manifest(storage, "bhcip_awards")
    assert m["row_count"] == 3

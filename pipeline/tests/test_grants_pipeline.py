"""End-to-end pipeline test on a small fixture CSV, local storage, no network."""

import json

import pytest

from cadollar.config import Settings
from cadollar.ingest.csv_download import QualityGateError, run_csv_ingest
from cadollar.publish.grants import publish_grants_summary
from cadollar.sources import load_source
from cadollar.storage import LocalStorage, read_manifest
from cadollar.transform.grants_portal import cleanse

HEADER = (
    "PortalID,GrantID,Status,LastUpdated,ChangeNotes,AgencyDept,Title,Type,LOI,Categories,"
    "CategorySuggestion,Purpose,Description,ApplicantType,ApplicantTypeNotes,Geography,"
    "FundingSource,FundingSourceNotes,MatchingFunds,MatchingFundsNotes,EstAvailFunds,"
    "EstAwards,EstAmounts,FundingMethod,FundingMethodNotes,OpenDate,ApplicationDeadline,"
    "AwardPeriod,ExpAwardDate,ElecSubmission,GrantURL,AgencyURL,AgencySubscribeURL,"
    "GrantEventsURL,ContactInfo,AwardStats"
)


def _row(pid: str, status: str, funds: str, category: str = "Environment & Water") -> str:
    return (
        f'{pid},,{status},"2026-07-14 01:00:00",,"Dept of Test","Grant {pid}",Grant,No,'
        f'"{category}",,Purpose,Desc,Nonprofit,,Statewide,State,,No,,"{funds}",,,'
        f'Reimbursement,,2026-01-01,,,,"Yes",https://example.gov,,,,,'
    )


def _csv(rows: list[str]) -> bytes:
    return ("﻿" + HEADER + "\n" + "\n".join(rows) + "\n").encode()


@pytest.fixture
def env(tmp_path, monkeypatch):
    settings = Settings(storage_mode="local", data_dir=tmp_path)
    storage = LocalStorage(tmp_path)
    cfg = load_source(settings, "grants_portal").model_copy(
        update={"min_rows": 2, "max_row_drop_pct": 50.0}
    )
    fetched: dict[str, bytes] = {}
    monkeypatch.setattr(
        "cadollar.ingest.csv_download.fetch_bytes", lambda url, **kw: fetched["body"]
    )
    return settings, storage, cfg, fetched


def test_ingest_cleanse_publish(env):
    _, storage, cfg, fetched = env
    fetched["body"] = _csv(
        [_row("1", "active", "$1,000,000"), _row("2", "active", ""), _row("3", "closed", "$5")]
    )

    result = run_csv_ingest(storage, cfg, cleanse)
    assert result.changed and result.row_count == 3
    assert storage.exists(result.raw_key)

    publish_grants_summary(storage, cfg)
    doc = json.loads(storage.get_bytes("published/grants_summary.json"))

    # provenance envelope is mandatory
    assert doc["source"]["name"] == "California Grants Portal"
    assert doc["as_of"] and doc["coverage_flag"] == "traceable"

    active = next(t for t in doc["data"]["totals_by_status"] if t["status"] == "active")
    # fail-honest: blank amount counted as unknown, NOT folded in as zero
    assert active["grant_count"] == 2
    assert active["est_avail_funds_known_usd"] == 1_000_000.0
    assert active["funds_unknown_count"] == 1


def test_unchanged_content_is_noop(env):
    _, storage, cfg, fetched = env
    fetched["body"] = _csv([_row("1", "active", "$1"), _row("2", "active", "$2")])
    assert run_csv_ingest(storage, cfg, cleanse).changed
    ingested_at = read_manifest(storage, cfg.source)["ingested_at"]

    assert not run_csv_ingest(storage, cfg, cleanse).changed
    m = read_manifest(storage, cfg.source)
    assert m["ingested_at"] == ingested_at  # nothing rewritten
    assert m["checked_at"] >= ingested_at


def test_row_drop_gate_keeps_last_good(env):
    _, storage, cfg, fetched = env
    fetched["body"] = _csv([_row(str(i), "active", "$1") for i in range(1, 11)])
    assert run_csv_ingest(storage, cfg, cleanse).row_count == 10

    fetched["body"] = _csv([_row("1", "active", "$1"), _row("2", "active", "$1")])
    with pytest.raises(QualityGateError):
        run_csv_ingest(storage, cfg, cleanse)
    # last-good manifest untouched
    assert read_manifest(storage, cfg.source)["row_count"] == 10

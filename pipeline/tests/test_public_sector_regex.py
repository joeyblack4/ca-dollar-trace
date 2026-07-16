"""The public-sector classifier is a published heuristic — pin its behavior
against real vendor names so pattern edits can't silently reclassify dollars."""

import duckdb
import pytest

from cadollar.ingest.fiscal_vendor import PUBLIC_SECTOR_SQL

PUBLIC = [
    "DEPARTMENT OF TECHNOLOGY",
    "DEPT OF PUBLIC HEALTH",
    "TREASURER OF LOS ANGELES CNTY",
    "COUNTY OF SAN DIEGO",
    "CITY OF SACRAMENTO",
    "CITY & COUNTY OF SAN FRANCISCO",
    "REGENTS OF UNIV OF CA DAVIS",
    "UNIVERSITY OF CALIFORNIA",
    "SAN DIEGO STATE UNIVERSITY",
    "LOS ANGELES UNIFIED SCHOOL DIST",
    "METROPOLITAN WATER DISTRICT",
    "LOS ANGELES COUNTY METROPOLITAN TRANSPORTATION AUTH",
    "JUDICIAL COUNCIL OF CALIFORNIA",
    "SUPERIOR COURT OF ORANGE COUNTY",
    "SACRAMENTO HOUSING AUTHORITY",
]

PRIVATE = [
    "CITY OF HOPE NATIONAL MEDICAL CENTER",  # private hospital
    "UNIFIED GROCERS INC",
    "UNIFIED PARKING SERVICES INC",
    "GOLDEN STATE WATER DISTRIBUTION LLC",
    "PACIFIC SANITATION DISTRIBUTORS",
    "ADVOCATES FOR HUMAN POTENTIAL",
    "PRIME THERAPEUTICS STATE",
    "CHILD CARE RESOURCE CENTER INC",
    "PRIDE INDUSTRIES ONE INC",
    "MCCARTHY BUILDING COS INC",
    "DELOITTE CONSULTING LLP",
    "OFFICE OF THE PRESIDENT LLC",  # hypothetical private firm
    "DOUGLAS C HAHN INSPECTION",
]


def _classify(name: str) -> bool:
    expr = PUBLIC_SECTOR_SQL.format(col="?")  # {col} appears twice (match + exceptions)
    (result,) = (
        duckdb.connect(":memory:")
        .execute(f"SELECT {expr}", [name.upper(), name.upper()])
        .fetchone()
    )
    return bool(result)


@pytest.mark.parametrize("name", PUBLIC)
def test_public_entities_flagged(name):
    assert _classify(name), f"{name} should classify as public sector"


@pytest.mark.parametrize("name", PRIVATE)
def test_private_vendors_not_flagged(name):
    assert not _classify(name), f"{name} should NOT classify as public sector"

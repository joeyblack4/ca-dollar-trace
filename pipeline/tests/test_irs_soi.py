"""irs_soi builder tests: federal-lens shape, correspondence + identity gates."""

import pytest

from cadollar.ingest.csv_download import QualityGateError
from cadollar.ingest.irs_soi import build_federal_lens_doc

CA_COUNTIES = [f"C{i:02d} County" for i in range(58)]


def _county_row(name, stub, n1, elderly, single=10, joint=5, hoh=2, agi=100):
    return {
        "STATE": "CA",
        "COUNTYNAME": name,
        "agi_stub": str(stub),
        "N1": str(n1),
        "ELDERLY": str(elderly),
        "mars1": str(single),
        "MARS2": str(joint),
        "MARS4": str(hoh),
        "A00100": str(agi),
    }


def _county_rows():
    rows = []
    for name in CA_COUNTIES + ["California"]:
        for stub in range(1, 9):
            rows.append(_county_row(name, stub, n1=100, elderly=25))
    return rows


def _mig_row(stub, inflow, outflow, nonmig=1000, samest=50):
    r = {"state": "CA", "agi_stub": str(stub)}
    for age in range(7):
        r[f"inflow_n1_{age}"] = str(inflow)
        r[f"outflow_n1_{age}"] = str(outflow)
        r[f"nonmig_n1_{age}"] = str(nonmig)
        r[f"samest_n1_{age}"] = str(samest)
        r[f"total_n1_{age}"] = str(nonmig + samest + inflow)
        r[f"inflow_y2_agi_{age}"] = "500"
        r[f"outflow_y2_agi_{age}"] = "800"
    return r


def _mig_rows():
    return [_mig_row(stub, inflow=20, outflow=30) for stub in range(8)]


def _mig_editions():
    older = [_mig_row(stub, inflow=10, outflow=40) for stub in range(8)]
    return [("2122", older), ("2223", _mig_rows())]


def _ftb():
    # statewide gate compares the IRS "California" rows (8 stubs x 100 = 800
    # returns) against the FTB total: 58 x 14 = 812 -> ratio 0.985, in band
    return {name.removesuffix(" County"): 14 for name in CA_COUNTIES}


def build(**overrides):
    kwargs = dict(
        county_rows=_county_rows(),
        mig_editions=_mig_editions(),
        ftb_counties=_ftb(),
    )
    kwargs.update(overrides)
    return build_federal_lens_doc(**kwargs)


def test_statewide_and_counties_shaped():
    doc = build()
    assert len(doc["statewide_by_class"]) == 8
    assert doc["statewide_by_class"][0]["elderly_pct"] == 25.0
    assert len(doc["counties"]) == 58
    c0 = doc["counties"][0]
    assert c0["county"] == "C00"  # " County" suffix stripped
    assert c0["correspondence"]["ratio"] == round(800 / 14, 3)
    assert doc["statewide_totals"]["ratio"] == round(800 / (58 * 14), 3)


def test_migration_flows_and_agi_units():
    doc = build()
    m = doc["migration"]
    assert m["years"] == "2022\u219223"  # detail comes from the NEWEST edition
    assert m["net_returns"] == -10
    assert m["inflow_agi_usd"] == 500_000  # $ thousands -> dollars
    assert len(m["by_income"]) == 7
    assert len(m["by_age"]) == 6
    assert all(r["net_returns"] == -10 for r in m["by_income"])
    # trend is oldest -> newest with per-edition nets
    assert [t["years"] for t in m["trend"]] == ["2021\u219222", "2022\u219223"]
    assert [t["net_returns"] for t in m["trend"]] == [-30, -10]


def test_elderly_exceeding_returns_refuses():
    rows = _county_rows()
    rows[0]["ELDERLY"] = "500"  # > N1=100
    with pytest.raises(QualityGateError, match="elderly"):
        build(county_rows=rows)


def test_correspondence_ratio_band_refuses():
    with pytest.raises(QualityGateError, match="ratio"):
        build(ftb_counties={k: 100 for k in _ftb()})  # IRS would be 8x FTB


def test_migration_identity_refuses():
    editions = _mig_editions()
    editions[1][1][0]["total_n1_0"] = "999999"
    with pytest.raises(QualityGateError, match="identity"):
        build(mig_editions=editions)


def test_suppressed_cells_parse_as_zero_not_crash():
    rows = _county_rows()
    rows[0]["ELDERLY"] = "d"  # IRS suppression marker
    doc = build(county_rows=rows)
    assert doc is not None

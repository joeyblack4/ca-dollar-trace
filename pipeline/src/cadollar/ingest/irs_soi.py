"""IRS SOI federal lens for California PIT: age, filing status, migration.

Publishes published/revenue/pit_federal_lens.json from two IRS files:
  county:    22incyallagi.csv — county × 8 AGI classes with the ELDERLY flag
             (primary taxpayer 60+) and marital-status counts
  migration: 2122migrationdata.zip → the gross-migration CSV: state × AGI
             class × age band, inflow/outflow/nonmigrant returns and AGI

Fail-honest rules — this doc exists to complete the demographic story WITHOUT
conflating federal and state numbers:
  - every figure here is a federal-return statistic; the site renders them
    only inside badged "federal lens" panels
  - the per-county correspondence ratio (IRS returns / FTB returns) is
    computed against the already-published pit.json and published per county;
    a statewide ratio outside 0.90-1.20 aborts the publish
  - the migration file's own identity (total = nonmigrant + same-state
    movers + inflows) must hold exactly-ish or the publish aborts
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import UTC, datetime
from typing import Any

import httpx

from ..config import Settings
from ..publish.envelope import envelope
from ..sources import SourceConfig
from ..storage import Storage, read_manifest, write_manifest
from .csv_download import QualityGateError
from .http import fetch_bytes

STATEWIDE = "California"

# 22incyallagi.csv agi_stub -> label (verified against per-stub average AGI)
COUNTY_STUBS = {
    1: "Under $1 (net losses)",
    2: "$1 – $9,999",
    3: "$10,000 – $24,999",
    4: "$25,000 – $49,999",
    5: "$50,000 – $74,999",
    6: "$75,000 – $99,999",
    7: "$100,000 – $199,999",
    8: "$200,000 and over",
}

# gross-migration agi_stub -> label (0 = all incomes)
MIGRATION_STUBS = {
    1: "Under $10,000",
    2: "$10,000 – $24,999",
    3: "$25,000 – $49,999",
    4: "$50,000 – $74,999",
    5: "$75,000 – $99,999",
    6: "$100,000 – $199,999",
    7: "$200,000 and over",
}

# age suffix in migration columns (0 = all ages)
MIGRATION_AGES = {
    1: "Under 26",
    2: "26 – 34",
    3: "35 – 44",
    4: "45 – 54",
    5: "55 – 64",
    6: "65 and over",
}

K = 1_000  # IRS dollar fields arrive in $ thousands


def _f(v: str | None) -> float:
    if v is None or v.strip() in ("", "d"):  # 'd' = suppressed small cell
        return 0.0
    return float(v)


def _edition(end_year: int) -> str:
    """Filing-year pair -> IRS file token: 2023 -> '2223' (2022-to-2023 edition)."""
    return f"{(end_year - 1) % 100:02d}{end_year % 100:02d}"


def run_irs_soi(storage: Storage, cfg: SourceConfig, settings: Settings) -> list[str]:
    now = datetime.now(UTC)
    as_of = now.strftime("%Y-%m-%dT%H%M%SZ")
    manifest = read_manifest(storage, cfg.source)
    trend_len = int(cfg.extra.get("trend_editions", 5))

    county_raw = fetch_bytes(cfg.endpoints["county"])

    # newest-first probe: the freshest edition the IRS has actually published
    # becomes the detail year, plus trailing editions for the trend series —
    # a single-year snapshot of migration would over- or under-state the story
    editions: list[tuple[str, bytes]] = []
    for end_year in range(now.year, now.year - 10, -1):
        token = _edition(end_year)
        try:
            editions.append((token, fetch_bytes(cfg.endpoints["migration"].format(edition=token))))
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                continue
            raise
        if len(editions) == trend_len:
            break
    if len(editions) < 2:
        raise QualityGateError(f"{cfg.source}: only {len(editions)} migration editions found")
    editions.reverse()  # oldest -> newest

    content_hash = hashlib.sha256(
        county_raw + b"".join(raw for _, raw in editions)
    ).hexdigest()
    if manifest.get("content_hash") == content_hash:
        manifest["checked_at"] = now.isoformat()
        write_manifest(storage, cfg.source, manifest)
        print(f"{cfg.source}: unchanged upstream, no-op")
        return manifest.get("published_keys", [])

    storage.put_bytes(f"raw/{cfg.source}/{cfg.dataset}/{as_of}/county.csv", county_raw, "text/csv")
    for token, raw in editions:
        storage.put_bytes(
            f"raw/{cfg.source}/{cfg.dataset}/{as_of}/migration_{token}.csv", raw, "text/csv"
        )

    county_rows = list(csv.DictReader(io.StringIO(county_raw.decode("latin-1"))))
    mig_editions = [
        (token, list(csv.DictReader(io.StringIO(raw.decode("latin-1")))))
        for token, raw in editions
    ]

    doc = build_federal_lens_doc(
        county_rows,
        mig_editions,
        ftb_counties=_load_ftb_counties(storage),
    )

    key = "published/revenue/pit_federal_lens.json"
    storage.put_bytes(
        key,
        json.dumps(
            envelope(cfg, as_of=as_of, ingested_at=now.isoformat(), data=doc), indent=2
        ).encode(),
        "application/json",
    )
    write_manifest(
        storage,
        cfg.source,
        {
            "content_hash": content_hash,
            "row_count": len(doc["counties"]) + len(doc["statewide_by_class"]),
            "as_of": as_of,
            "ingested_at": now.isoformat(),
            "checked_at": now.isoformat(),
            "published_keys": [key],
        },
    )
    latest = doc["migration"]["trend"][-1]
    print(
        f"{cfg.source}: {len(doc['counties'])} counties; migration {latest['years']} "
        f"net {latest['net_returns']:+,} returns ({len(doc['migration']['trend'])} editions)"
    )
    return [key]


def _load_ftb_counties(storage: Storage) -> dict[str, int]:
    """FTB per-county return counts from the already-published pit.json."""
    raw = storage.get_bytes("published/revenue/pit.json")
    if raw is None:
        from ..config import REPO_ROOT

        committed = REPO_ROOT / "site" / "public" / "data" / "revenue" / "pit.json"
        if committed.exists():
            raw = committed.read_bytes()
        else:
            raise QualityGateError("irs_soi requires revenue/pit.json; run ftb_pit first")
    data = json.loads(raw)["data"]
    return {c["county"]: c["returns"] for c in data["counties"]}


def _edition_label(token: str) -> str:
    """'2223' -> '2022→23' (consecutive filing years)."""
    y1, y2 = int(token[:2]), int(token[2:])
    century = 2000 if y1 < 90 else 1900
    return f"{century + y1}→{y2:02d}"


def build_federal_lens_doc(
    county_rows: list[dict[str, str]],
    mig_editions: list[tuple[str, list[dict[str, str]]]],
    ftb_counties: dict[str, int],
) -> dict[str, Any]:
    ca = [r for r in county_rows if r.get("STATE") == "CA"]
    if not ca:
        raise QualityGateError("irs_soi: no CA rows in county file")

    def _classes(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
        out = []
        for r in sorted(rows, key=lambda x: int(x["agi_stub"])):
            stub = int(r["agi_stub"])
            n1 = _f(r["N1"])
            elderly = _f(r["ELDERLY"])
            if elderly > n1:
                raise QualityGateError(f"irs_soi: elderly {elderly} > returns {n1} (stub {stub})")
            single, joint, hoh = _f(r["mars1"]), _f(r["MARS2"]), _f(r["MARS4"])
            out.append(
                {
                    "label": COUNTY_STUBS[stub],
                    "returns": int(n1),
                    "elderly_returns": int(elderly),
                    "elderly_pct": round(elderly / n1 * 100, 1) if n1 else 0,
                    "single": int(single),
                    "joint": int(joint),
                    "head_of_household": int(hoh),
                    "other_status": max(0, int(n1 - single - joint - hoh)),
                    "agi_usd": int(_f(r["A00100"]) * K),
                }
            )
        if len(out) != len(COUNTY_STUBS):
            raise QualityGateError(f"irs_soi: {len(out)} AGI classes, expected {len(COUNTY_STUBS)}")
        return out

    statewide = _classes([r for r in ca if r["COUNTYNAME"] == STATEWIDE])
    counties = []
    for name in sorted({r["COUNTYNAME"] for r in ca} - {STATEWIDE}):
        classes = _classes([r for r in ca if r["COUNTYNAME"] == name])
        short = name.removesuffix(" County")
        total = sum(c["returns"] for c in classes)
        elderly = sum(c["elderly_returns"] for c in classes)
        ftb = ftb_counties.get(short)
        counties.append(
            {
                "county": short,
                "returns": total,
                "elderly_returns": elderly,
                "elderly_pct": round(elderly / total * 100, 1) if total else 0,
                "classes": classes,
                "correspondence": {
                    "irs_returns": total,
                    "ftb_returns": ftb,
                    "ratio": round(total / ftb, 3) if ftb else None,
                },
            }
        )
    if len(counties) != 58:
        raise QualityGateError(f"irs_soi: {len(counties)} counties, expected 58")

    irs_total = sum(c["returns"] for c in statewide)
    ftb_total = sum(v for v in ftb_counties.values())
    ratio = irs_total / ftb_total if ftb_total else 0
    if not 0.90 <= ratio <= 1.20:
        raise QualityGateError(
            f"irs_soi: statewide IRS/FTB return ratio {ratio:.3f} outside sanity band — "
            "these should be nearly the same people"
        )

    # ---- migration: trend across editions + age × income detail for newest ----
    def _flow(r: dict[str, str], age: int) -> dict[str, Any]:
        inflow = int(_f(r[f"inflow_n1_{age}"]))
        outflow = int(_f(r[f"outflow_n1_{age}"]))
        return {
            "inflow_returns": inflow,
            "outflow_returns": outflow,
            "net_returns": inflow - outflow,
            "inflow_agi_usd": int(_f(r[f"inflow_y2_agi_{age}"]) * K),
            "outflow_agi_usd": int(_f(r[f"outflow_y2_agi_{age}"]) * K),
        }

    def _ca_rows(mig_rows: list[dict[str, str]], token: str) -> list[dict[str, str]]:
        ca_mig = [r for r in mig_rows if r.get("state") == "CA"]
        if len(ca_mig) != 8:  # stub 0 (all) + 7 classes
            raise QualityGateError(
                f"irs_soi: {len(ca_mig)} CA migration rows in edition {token}, expected 8"
            )
        all_row = next(r for r in ca_mig if r["agi_stub"] == "0")
        total0 = _f(all_row["total_n1_0"])
        identity = (
            _f(all_row["nonmig_n1_0"]) + _f(all_row["samest_n1_0"]) + _f(all_row["inflow_n1_0"])
        )
        if total0 and abs(identity - total0) / total0 > 0.001:
            raise QualityGateError(
                f"irs_soi: migration identity fails in edition {token} — "
                f"total {total0} vs components {identity}"
            )
        return ca_mig

    trend = []
    for token, mig_rows in mig_editions:  # oldest -> newest
        ca_mig = _ca_rows(mig_rows, token)
        all_row = next(r for r in ca_mig if r["agi_stub"] == "0")
        flow = _flow(all_row, 0)
        trend.append(
            {
                "years": _edition_label(token),
                **flow,
                "net_agi_usd": flow["inflow_agi_usd"] - flow["outflow_agi_usd"],
            }
        )

    latest_token, latest_rows = mig_editions[-1]
    latest_ca = _ca_rows(latest_rows, latest_token)
    latest_all = next(r for r in latest_ca if r["agi_stub"] == "0")
    by_income = [
        {"label": MIGRATION_STUBS[int(r["agi_stub"])], **_flow(r, 0)}
        for r in sorted(latest_ca, key=lambda x: int(x["agi_stub"]))
        if r["agi_stub"] != "0"
    ]
    by_age = [{"label": lbl, **_flow(latest_all, a)} for a, lbl in MIGRATION_AGES.items()]
    overall = _flow(latest_all, 0)
    migration_years = _edition_label(latest_token)

    return {
        "framing": (
            "Federal (IRS) return statistics for the same Californians — shown as a "
            "demographic lens only, never combined with California tax figures."
        ),
        "tax_year": 2022,
        "statewide_by_class": statewide,
        "statewide_totals": {
            "irs_returns": irs_total,
            "ftb_returns": ftb_total,
            "ratio": round(ratio, 3),
            "note": (
                "IRS counts slightly more filers than FTB — federal filers under "
                "California's filing threshold. Near-1 ratio is the evidence these "
                "tables describe the same people."
            ),
        },
        "counties": counties,
        "migration": {
            "years": migration_years,
            **overall,
            "net_agi_usd": overall["inflow_agi_usd"] - overall["outflow_agi_usd"],
            "by_income": by_income,
            "by_age": by_age,
            "trend": trend,
            "trend_note": (
                "One year of migration is a snapshot, not a verdict — read the trend. "
                "The IRS enhanced its return-matching process starting with the "
                "2022→23 edition, so the newest figure is not perfectly comparable "
                "to earlier years."
            ),
        },
    }

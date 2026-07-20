"""SEC XBRL frames: what public companies self-report as state+local tax expense.

Publishes published/revenue/corp_public_companies.json — the deepest truthful
named-company layer that exists. California cannot publish per-company tax
(R&TC §19542); SEC registrants disclose their own current state-and-local
income tax expense in 10-Ks. ALL states combined, self-reported, accrual.

Fail-honest rules:
  - plausibility screen: a company whose state+local expense wildly exceeds
    its own TOTAL income tax expense (same frame year) is an XBRL tagging
    error — excluded and COUNTED, never corrected or imputed
  - the frame year is chosen as the newest calendar year with robust coverage
    (>= min_rows companies), so a thin early-cycle frame never silently
    replaces a full one
  - hq_state comes from each company's own EDGAR submissions record; a fetch
    failure leaves it null rather than guessing
"""

from __future__ import annotations

import hashlib
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

# SEC blocks requests without a declared contact (https://www.sec.gov/os/accessing-edgar-data)
SEC_USER_AGENT = "ca-dollar-trace (public-interest CA budget transparency; contact: joey@black4.ai)"

# state tax > PLAUSIBILITY_MULT × |total income tax| + PLAUSIBILITY_FLOOR
# means a tagging error (e.g. dollars-vs-thousands), not a real filing
PLAUSIBILITY_MULT = 10
PLAUSIBILITY_FLOOR = 5_000_000


def run_sec_state_tax(storage: Storage, cfg: SourceConfig, settings: Settings) -> list[str]:
    now = datetime.now(UTC)
    as_of = now.strftime("%Y-%m-%dT%H%M%SZ")
    manifest = read_manifest(storage, cfg.source)
    top_n = int(cfg.extra.get("top_n", 100))

    # newest calendar-year frame with robust coverage
    frame = None
    frame_year = None
    for year in range(now.year - 1, now.year - 4, -1):
        try:
            candidate = json.loads(
                fetch_bytes(cfg.endpoints["frame"].format(year=year), user_agent=SEC_USER_AGENT)
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                continue
            raise
        if len(candidate.get("data", [])) >= cfg.min_rows:
            frame, frame_year = candidate, year
            break
    if frame is None or frame_year is None:
        raise QualityGateError(
            f"{cfg.source}: no calendar-year frame with >= {cfg.min_rows} companies"
        )

    totals_raw = json.loads(
        fetch_bytes(cfg.endpoints["total_frame"].format(year=frame_year), user_agent=SEC_USER_AGENT)
    )
    total_by_cik = {r["cik"]: r["val"] for r in totals_raw.get("data", [])}

    content_hash = hashlib.sha256(
        json.dumps([frame_year, frame["data"]], sort_keys=True).encode()
    ).hexdigest()
    if manifest.get("content_hash") == content_hash:
        manifest["checked_at"] = now.isoformat()
        write_manifest(storage, cfg.source, manifest)
        print(f"{cfg.source}: unchanged upstream, no-op")
        return manifest.get("published_keys", [])

    storage.put_bytes(
        f"raw/{cfg.source}/{cfg.dataset}/{as_of}/frame_cy{frame_year}.json",
        json.dumps(frame).encode(),
        "application/json",
    )

    kept, excluded = screen_companies(frame["data"], total_by_cik)
    kept.sort(key=lambda r: -r["val"])
    top = kept[:top_n]

    # enrich the published slice with HQ state + ticker from EDGAR submissions
    companies = []
    for r in top:
        hq_state = None
        ticker = None
        try:
            sub = json.loads(
                fetch_bytes(
                    cfg.endpoints["submissions"].format(cik=r["cik"]), user_agent=SEC_USER_AGENT
                )
            )
            hq_state = (sub.get("addresses", {}).get("business", {}) or {}).get("stateOrCountry")
            tickers = sub.get("tickers") or []
            ticker = tickers[0] if tickers else None
        except Exception:
            pass  # enrichment only — a miss stays null, never guessed
        companies.append(
            {
                "company": r["entityName"],
                "cik": r["cik"],
                "ticker": ticker,
                "hq_state": hq_state,
                "ca_hq": hq_state == "CA",
                "state_local_tax_expense_usd": r["val"],
                "total_income_tax_expense_usd": total_by_cik.get(r["cik"]),
            }
        )

    doc = {
        "calendar_year": frame_year,
        "companies": companies,
        "universe": {
            "companies_reporting": len(frame["data"]),
            "excluded_implausible": excluded,
            "shown": len(companies),
            "screen_rule": (
                f"excluded where state+local expense > {PLAUSIBILITY_MULT}x the company's "
                f"own total income tax expense + ${PLAUSIBILITY_FLOOR:,} (XBRL tagging "
                "errors), or where no total was reported to check against"
            ),
        },
        "measure_note": (
            "Current state AND local income tax expense across ALL U.S. states, as each "
            "company reported it to the SEC — accrual expense, not cash paid. The "
            "California share is confidential by law (R&TC §19542) and cannot be derived."
        ),
    }

    key = "published/revenue/corp_public_companies.json"
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
            "row_count": len(companies),
            "as_of": as_of,
            "ingested_at": now.isoformat(),
            "checked_at": now.isoformat(),
            "published_keys": [key],
        },
    )
    print(
        f"{cfg.source}: CY{frame_year} — {len(companies)} companies "
        f"({excluded} excluded as implausible)"
    )
    return [key]


def screen_companies(
    rows: list[dict[str, Any]], total_by_cik: dict[int, float]
) -> tuple[list[dict[str, Any]], int]:
    """Split frame rows into plausible vs tagging-error filings."""
    kept: list[dict[str, Any]] = []
    excluded = 0
    for r in rows:
        if r["val"] <= 0:
            continue  # benefits/zero: not part of a "top payers" list
        total = total_by_cik.get(r["cik"])
        if total is None or r["val"] > PLAUSIBILITY_MULT * abs(total) + PLAUSIBILITY_FLOOR:
            excluded += 1
            continue
        kept.append(r)
    return kept, excluded

"""FAC single audits: every CA entity spending $1M+ in federal money, audited.

Pulls the `general` table for California for the two most recent audit years,
publishes the latest substantially-complete year: named auditees with their
audited federal expenditures — schools, counties, nonprofits, health systems.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from typing import Any

import httpx
import stamina

from ..config import Settings
from ..publish.envelope import envelope
from ..sources import SourceConfig
from ..storage import Storage, read_manifest, write_manifest
from .csv_download import QualityGateError
from .http import USER_AGENT, TransientHTTPError

SUBSTANTIAL = 2500  # a "complete-enough" CA audit year has thousands of filings


@stamina.retry(on=TransientHTTPError, attempts=4, timeout=300)
def _fac_get(url: str, params: dict[str, str]) -> list[dict[str, Any]]:
    key = os.environ.get("CDT_FAC_API_KEY", "DEMO_KEY")
    try:
        resp = httpx.get(
            url,
            params=params,
            timeout=120,
            headers={"X-Api-Key": key, "User-Agent": USER_AGENT},
        )
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        raise TransientHTTPError(str(e)) from e
    if resp.status_code == 429 or resp.status_code >= 500:
        raise TransientHTTPError(f"HTTP {resp.status_code}")
    resp.raise_for_status()
    return resp.json()


def run_fac_sefa(storage: Storage, cfg: SourceConfig, settings: Settings) -> str:
    now = datetime.now(UTC)
    as_of = now.strftime("%Y-%m-%dT%H%M%SZ")
    manifest = read_manifest(storage, cfg.source)

    def fetch_year(y: int) -> list[dict[str, Any]]:
        return _fac_get(
            cfg.endpoints["general"],
            {
                "select": "report_id,auditee_name,auditee_uei,entity_type,"
                "total_amount_expended,fac_accepted_date",
                "audit_year": f"eq.{y}",
                "auditee_state": "eq.CA",
                "limit": "20000",
            },
        )

    def total(rows: list[dict[str, Any]]) -> float:
        return sum(float(r.get("total_amount_expended") or 0) for r in rows)

    # completeness is judged in DOLLARS, not filings: the State of California's
    # own single audit dwarfs everything, so a year without it is "in progress"
    year = now.year
    years: list[tuple[int, list[dict[str, Any]]]] = []
    for y in range(year, year - 5, -1):
        rows = fetch_year(y)
        if rows:
            years.append((y, rows))
        if len(years) >= 3:
            break
    if not years:
        raise QualityGateError(f"{cfg.source}: no CA audit filings found")
    # cascade: keep dropping the newest year while it holds <60% of the
    # dollars of the year beneath it (still filling in)
    partial_note = None
    while len(years) >= 2 and total(years[0][1]) < 0.6 * total(years[1][1]):
        y0, r0 = years.pop(0)
        note = (
            f"audit year {y0} is still filling in ({len(r0)} filings, "
            f"${total(r0) / 1e9:.0f}B so far)"
        )
        partial_note = note if partial_note is None else f"{partial_note}; {note}"
    audit_year, rows = years[0]
    if len(rows) < cfg.min_rows:
        raise QualityGateError(f"{cfg.source}: only {len(rows)} filings")

    blob = json.dumps(rows, sort_keys=True).encode()
    content_hash = hashlib.sha256(blob).hexdigest()
    if manifest.get("content_hash") == content_hash:
        manifest["checked_at"] = now.isoformat()
        write_manifest(storage, cfg.source, manifest)
        print(f"{cfg.source}: unchanged upstream, no-op")
        return manifest["published_key"]

    storage.put_bytes(
        f"raw/{cfg.source}/{cfg.dataset}/{as_of}/general_{audit_year}.json",
        blob,
        "application/json",
    )

    for r in rows:
        r["total_amount_expended"] = float(r.get("total_amount_expended") or 0)
    rows.sort(key=lambda r: -r["total_amount_expended"])

    by_type: dict[str, dict[str, float]] = {}
    for r in rows:
        t = r.get("entity_type") or "unknown"
        agg = by_type.setdefault(t, {"count": 0, "usd": 0.0})
        agg["count"] += 1
        agg["usd"] += r["total_amount_expended"]

    doc = {
        "audit_year": audit_year,
        "in_progress_note": partial_note,
        "entity_count": len(rows),
        "total_federal_expended_usd": sum(r["total_amount_expended"] for r in rows),
        "by_entity_type": [
            {"entity_type": t, **v}
            for t, v in sorted(by_type.items(), key=lambda kv: -kv[1]["usd"])
        ],
        "top_auditees_limit": 60,
        "top_auditees": [
            {
                "name": r["auditee_name"],
                "uei": r.get("auditee_uei"),
                "entity_type": r.get("entity_type"),
                "federal_expended_usd": r["total_amount_expended"],
                "report_id": r["report_id"],
            }
            for r in rows[:60]
        ],
    }

    key = "published/federal_audits.json"
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
            "row_count": len(rows),
            "as_of": as_of,
            "ingested_at": now.isoformat(),
            "checked_at": now.isoformat(),
            "published_key": key,
        },
    )
    print(f"{cfg.source}: {len(rows)} audits (AY{audit_year}) -> {key}")
    return key

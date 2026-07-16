"""Grant awards connector: the actual awardees (AB 132 post-award data).

Three per-FY CSVs -> combined cleansed parquet -> published summary with the
subrecipient-flag visibility split: for every dollar awarded, does the public
record end at the recipient (no subrecipients) or is there a known-but-unnamed
next hop (subrecipients exist, identities not collected)?
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from ..config import Settings
from ..publish.envelope import envelope
from ..sources import SourceConfig
from ..storage import Storage, read_manifest, write_manifest
from .csv_download import QualityGateError
from .http import fetch_bytes

CLEANSE_SQL = """
CREATE OR REPLACE TABLE awards AS
SELECT
    PortalID                                        AS portal_id,
    FiscalYear                                      AS fiscal_year,
    AgencyDept                                      AS agency_dept,
    ProjectTitle                                    AS project_title,
    RecipientType                                   AS recipient_type,
    RecipientName                                   AS recipient_name,
    lower("Sub-recipients") = 'yes'                 AS has_subrecipients,
    TRY_CAST(NULLIF(regexp_replace(TotalAwardAmount, '[$,]', '', 'g'), '') AS DECIMAL(18,2))
                                                    AS award_usd,
    CountiesServed                                  AS counties_served,
    ProjectStatus                                   AS project_status,
    TRY_CAST(LastUpdated AS TIMESTAMP)              AS last_updated,
    ? AS _endpoint, ? AS _ingested_at
FROM read_csv(?, header=true, all_varchar=true);
"""


def run_grants_awards(storage: Storage, cfg: SourceConfig, settings: Settings) -> str:
    now = datetime.now(UTC)
    as_of = now.strftime("%Y-%m-%dT%H%M%SZ")
    manifest = read_manifest(storage, cfg.source)

    raw = {name: fetch_bytes(url) for name, url in sorted(cfg.endpoints.items())}
    content_hash = hashlib.sha256(b"".join(raw.values())).hexdigest()
    if manifest.get("content_hash") == content_hash:
        manifest["checked_at"] = now.isoformat()
        write_manifest(storage, cfg.source, manifest)
        print(f"{cfg.source}: unchanged upstream, no-op")
        return manifest["published_key"]

    conn = duckdb.connect(":memory:")
    total_rows = 0
    with tempfile.TemporaryDirectory() as td:
        frames = []
        for name, body in raw.items():
            storage.put_bytes(
                f"raw/{cfg.source}/{cfg.dataset}/{as_of}/{name}.csv", body, "text/csv"
            )
            p = Path(td) / f"{name}.csv"
            p.write_bytes(body)
            conn.execute(CLEANSE_SQL, [name, now.isoformat(), str(p)])
            conn.execute(f"CREATE TABLE awards_{name} AS SELECT * FROM awards")
            frames.append(f"SELECT * FROM awards_{name}")
        conn.execute(f"CREATE TABLE all_awards AS {' UNION ALL '.join(frames)}")
        (total_rows,) = conn.execute("SELECT count(*) FROM all_awards").fetchone()
        if total_rows < cfg.min_rows:
            raise QualityGateError(f"{cfg.source}: {total_rows} rows < {cfg.min_rows}")

        out = Path(td) / "awards.parquet"
        conn.execute(f"COPY all_awards TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)")
        storage.put_file(f"cleansed/{cfg.source}/awards.parquet", out)

    # --- the visibility split: where does each awarded dollar's trail end? ---
    by_fy = _rows(conn, """
        SELECT fiscal_year,
               count(*)                                        AS award_count,
               sum(award_usd)                                  AS awarded_known_usd,
               count(*) FILTER (award_usd IS NULL)             AS amount_unknown_count,
               sum(award_usd) FILTER (has_subrecipients)       AS with_subrecipients_usd,
               count(*) FILTER (has_subrecipients)             AS with_subrecipients_count,
               count(*) FILTER (has_subrecipients IS NULL)     AS subrecipient_flag_unknown_count
        FROM all_awards GROUP BY 1 ORDER BY 1""")
    top_recipients = _rows(conn, """
        SELECT recipient_name,
               any_value(recipient_type)                       AS recipient_type,
               count(*)                                        AS award_count,
               sum(award_usd)                                  AS awarded_usd,
               bool_or(has_subrecipients)                      AS any_subrecipients
        FROM all_awards GROUP BY 1 ORDER BY 4 DESC NULLS LAST LIMIT 100""")
    by_agency = _rows(conn, """
        SELECT agency_dept,
               count(*)                                        AS award_count,
               sum(award_usd)                                  AS awarded_usd,
               sum(award_usd) FILTER (has_subrecipients)       AS with_subrecipients_usd
        FROM all_awards GROUP BY 1 ORDER BY 3 DESC NULLS LAST LIMIT 40""")
    (agency_total, agencies_all_usd) = conn.execute(
        "SELECT count(DISTINCT agency_dept), sum(award_usd) FROM all_awards"
    ).fetchone()
    conn.close()

    shown_usd = sum(a["awarded_usd"] or 0 for a in by_agency)
    doc = {
        "by_fiscal_year": by_fy,
        "top_recipients": top_recipients,
        "top_recipients_limit": 100,
        "by_agency": by_agency,
        # disclosure: the by_agency list is a TOP-40, not the universe
        "by_agency_limit": 40,
        "agency_count_total": int(agency_total),
        "agencies_not_shown_usd": float(agencies_all_usd or 0) - shown_usd,
    }
    key = "published/grants_awards.json"
    storage.put_bytes(
        key,
        json.dumps(
            envelope(cfg, as_of=as_of, ingested_at=now.isoformat(), data=doc),
            indent=2,
            default=str,
        ).encode(),
        "application/json",
    )
    write_manifest(
        storage,
        cfg.source,
        {
            "content_hash": content_hash,
            "row_count": int(total_rows),
            "as_of": as_of,
            "ingested_at": now.isoformat(),
            "checked_at": now.isoformat(),
            "published_key": key,
        },
    )
    print(f"{cfg.source}: {total_rows} awards -> {key}")
    return key


def _rows(conn: duckdb.DuckDBPyConnection, sql: str) -> list[dict]:
    cur = conn.execute(sql)
    cols = [d[0] for d in cur.description]
    out = []
    for row in cur.fetchall():
        rec = dict(zip(cols, row))
        for k, v in rec.items():
            if hasattr(v, "quantize"):  # DECIMAL -> float for JSON
                rec[k] = float(v)
        out.append(rec)
    return out

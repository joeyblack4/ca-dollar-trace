"""Cleanse the Grants Portal opportunities CSV → typed parquet.

Column names are snake_cased; money strings ("$8,740,000") become DECIMAL;
blank amounts stay NULL (unknown ≠ zero). Provenance columns (_source,
_as_of, _content_hash) ride on every row.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import duckdb

CLEANSE_SQL = """
CREATE OR REPLACE TABLE cleansed AS
SELECT
    PortalID                                          AS portal_id,
    NULLIF(GrantID, '')                               AS grant_id,
    lower(Status)                                     AS status,
    TRY_CAST(LastUpdated AS TIMESTAMP)                AS last_updated,
    AgencyDept                                        AS agency_dept,
    Title                                             AS title,
    Type                                              AS grant_type,
    Categories                                        AS categories,
    Purpose                                           AS purpose,
    ApplicantType                                     AS applicant_type,
    Geography                                         AS geography,
    FundingSource                                     AS funding_source,
    -- '$8,740,000' -> 8740000 ; '' -> NULL (unknown, never zero)
    TRY_CAST(NULLIF(regexp_replace(EstAvailFunds, '[$,]', '', 'g'), '') AS DECIMAL(18,2))
                                                      AS est_avail_funds_usd,
    NULLIF(EstAvailFunds, '')                         AS est_avail_funds_raw,
    TRY_CAST(OpenDate AS DATE)                        AS open_date,
    NULLIF(ApplicationDeadline, '')                   AS application_deadline_raw,
    NULLIF(ExpAwardDate, '')                          AS exp_award_date_raw,
    GrantURL                                          AS grant_url,
    ? AS _source, ? AS _as_of, ? AS _content_hash
FROM read_csv(?, header=true, all_varchar=true);
"""


def cleanse(raw_csv: bytes, as_of: str, content_hash: str) -> tuple[bytes, int]:
    with tempfile.TemporaryDirectory() as td:
        csv_path = Path(td) / "in.csv"
        out_path = Path(td) / "out.parquet"
        csv_path.write_bytes(raw_csv)

        conn = duckdb.connect(":memory:")
        conn.execute(CLEANSE_SQL, ["grants_portal", as_of, content_hash, str(csv_path)])
        count_row = conn.execute("SELECT count(*) FROM cleansed").fetchone()
        assert count_row is not None
        (row_count,) = count_row
        conn.execute(f"COPY cleansed TO '{out_path}' (FORMAT PARQUET, COMPRESSION ZSTD)")
        conn.close()
        return out_path.read_bytes(), int(row_count)

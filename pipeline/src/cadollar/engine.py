"""DuckDB connection manager.

Ephemeral in-memory connections per job (batch-first: no persistent DB).
Loads httpfs/parquet/json extensions and, in r2 mode, configures S3-compatible
credentials so SQL can read/write parquet on R2 directly.
"""

from __future__ import annotations

import duckdb

from .config import Settings


def connect(settings: Settings) -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect(":memory:")
    conn.execute(f"SET memory_limit = '{settings.duckdb_memory_limit}'")
    conn.execute(f"SET threads = {settings.duckdb_threads}")
    for ext in ("httpfs", "parquet", "json"):
        conn.execute(f"INSTALL {ext}; LOAD {ext};")
    if settings.storage_mode == "r2":
        conn.execute(f"""
            CREATE OR REPLACE SECRET r2 (
                TYPE S3,
                KEY_ID '{settings.r2_access_key_id}',
                SECRET '{settings.r2_secret_access_key}',
                ENDPOINT '{settings.r2_account_id}.r2.cloudflarestorage.com',
                REGION 'auto',
                URL_STYLE 'path'
            );
        """)
    return conn

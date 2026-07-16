"""The provenance envelope every published number ships inside.

Fail-honest law: a figure without its source, as-of date, and coverage flag
does not get published. The site renders these as citation chips and badges.
"""

from __future__ import annotations

from typing import Any

from ..sources import SourceConfig


def envelope(
    cfg: SourceConfig, as_of: str, ingested_at: str, data: dict[str, Any]
) -> dict[str, Any]:
    return {
        "source": {
            "name": cfg.info.name,
            "publisher": cfg.info.publisher,
            "url": cfg.info.url,
            "license": cfg.info.license,
        },
        "as_of": as_of,
        "ingested_at": ingested_at,
        "cadence": cfg.cadence,
        "coverage_flag": cfg.coverage_flag,
        "caveats": cfg.caveats,
        "data": data,
    }

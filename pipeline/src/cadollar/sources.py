"""Declarative source configs: one YAML per source under pipeline/sources/."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel

from .config import Settings


class SourceInfo(BaseModel):
    """Provenance block published verbatim with every number derived from this source."""

    name: str
    publisher: str
    url: str
    license: str


class SourceConfig(BaseModel):
    source: str  # slug, e.g. "grants_portal"
    dataset: str  # dataset slug within the source
    access: str  # "csv_download" | "json_api" | "ckan" | "socrata" | ...
    download_url: str = ""  # single-file sources
    endpoints: dict[str, str] = {}  # multi-endpoint JSON sources (name -> url)
    cadence: str  # human-readable ("daily 8:45pm PT", "monthly, 60-day lag")
    freshness_sla_hours: int
    min_rows: int = 1
    max_row_drop_pct: float = 20.0
    coverage_flag: str = "traceable"  # traceable | category_only | trail_ends_here | masked
    caveats: list[str] = []
    info: SourceInfo


def load_source(settings: Settings, source: str) -> SourceConfig:
    path = settings.sources_dir / f"{source}.yaml"
    with open(path) as f:
        return SourceConfig.model_validate(yaml.safe_load(f))


def list_sources(settings: Settings) -> list[str]:
    return sorted(p.stem for p in Path(settings.sources_dir).glob("*.yaml"))

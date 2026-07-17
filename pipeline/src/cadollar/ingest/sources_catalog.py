"""Sources catalog: the public, always-accurate list of where every number
comes from. Derived, network-free — reads the declarative source configs
themselves (not their data), so the About page can never claim a source the
pipeline doesn't actually ingest, or drift from a config change.

Each external source is grouped into a resident-facing layer and given a
one-line description of what it feeds. The factual fields (publisher, URL,
cadence, coverage, caveats) come verbatim from the source config's own
provenance block. Purely derived crosswalks (entity resolution, search index)
are listed separately and labeled as computed from the others.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from ..config import Settings
from ..publish.envelope import envelope
from ..sources import SourceConfig, load_source
from ..storage import Storage, read_manifest, write_manifest

# resident-facing "what it feeds", keyed by source slug.
_FEEDS = {
    "ebudget_enacted": "The enacted state budget — what the Legislature appropriated, "
    "by fund and program area.",
    "ebudget_detail": "Department- and program-level detail beneath each agency's budget.",
    "fiscal_vendor": "The state's checkbook — actual vendor payments, name by name.",
    "grants_portal": "State grant programs open for application, refreshed nightly.",
    "grants_awards": "The organizations awarded state grants, and for how much.",
    "bhcip_awards": "Behavioral-health infrastructure grants and the projects they funded.",
    "compensation": "Government payroll — positions, wages, and benefits reported to the "
    "State Controller.",
    "medical_plans": "Medi-Cal managed-care enrollment and the certified rates paid per member.",
    "hospital_finances": "Every hospital's own annual financials — including what it reports "
    "receiving from Medi-Cal.",
    "county_finances": "County finances by category, self-reported to the State Controller.",
    "city_finances": "City finances by category, self-reported to the State Controller.",
    "district_finances": "Special-district finances by category, self-reported to the "
    "State Controller.",
    "sacs_k12": "K-12 school-district spending, self-reported unaudited actuals.",
    "k12_apportionment": "What the state certified it would pay each school district — the "
    "sending side of K-12 money.",
    "city_checkbooks": "Transaction-level checkbooks for the cities that publish one (LA & SF).",
    "usaspending_ca": "Federal awards flowing into California, with subaward hand-offs "
    "where reported.",
    "fac_sefa": "Independently audited federal spending (single audits) — the one audited source.",
    "federal_subawards": "Federal money re-granted to sub-recipients, one hop past the prime.",
    "nonprofits": "Charity registration standing and IRS Form 990 filings for nonprofits.",
    "nonprofit_officers": "Who runs each nonprofit and what they're paid — named officers "
    "from IRS Form 990.",
}

# display order: which sources sit under each resident-facing layer.
_LAYER = [
    ("The state budget", ["ebudget_enacted", "ebudget_detail"]),
    ("State spending", [
        "fiscal_vendor", "grants_portal", "grants_awards", "bhcip_awards",
        "compensation", "medical_plans", "hospital_finances",
    ]),
    ("Local government", [
        "county_finances", "city_finances", "district_finances", "sacs_k12",
        "k12_apportionment", "city_checkbooks",
    ]),
    ("Federal money", ["usaspending_ca", "fac_sefa", "federal_subawards"]),
    ("Recipient registries", ["nonprofits", "nonprofit_officers"]),
]

# derived crosswalks — computed FROM the sources above, not pulled from anywhere
_DERIVED = {
    "entities": "One organization unified across every source above, so its full footprint "
    "reads as a single profile.",
    "search_index": "The name-search index that jumps you straight to an organization's trail.",
}


def _entry(cfg: SourceConfig, layer: str, feeds: str) -> dict:
    return {
        "source": cfg.source,
        "name": cfg.info.name,
        "publisher": cfg.info.publisher,
        "url": cfg.info.url,
        "cadence": cfg.cadence,
        "coverage_flag": cfg.coverage_flag,
        "caveats": cfg.caveats,
        "layer": layer,
        "feeds": feeds,
    }


def run_sources_catalog(storage: Storage, cfg: SourceConfig, settings: Settings) -> str:
    now = datetime.now(UTC)
    as_of = now.strftime("%Y-%m-%dT%H%M%SZ")
    manifest = read_manifest(storage, cfg.source)

    sources = []
    for layer, members in _LAYER:
        for slug in members:
            sc = load_source(settings, slug)
            sources.append(_entry(sc, layer, _FEEDS[slug]))
    derived = [
        {"source": slug, "name": load_source(settings, slug).info.name, "feeds": feeds}
        for slug, feeds in _DERIVED.items()
    ]

    doc = {
        "source_count": len(sources),
        "layer_order": [layer for layer, _ in _LAYER],
        "sources": sources,
        "derived": derived,
    }
    if doc["source_count"] < cfg.min_rows:
        raise ValueError(f"{cfg.source}: only {doc['source_count']} sources catalogued")

    blob = json.dumps(doc, sort_keys=True, default=str).encode()
    content_hash = hashlib.sha256(blob).hexdigest()
    if manifest.get("content_hash") == content_hash:
        manifest["checked_at"] = now.isoformat()
        write_manifest(storage, cfg.source, manifest)
        print(f"{cfg.source}: unchanged, no-op")
        return manifest["published_key"]

    key = "published/sources_catalog.json"
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
            "row_count": doc["source_count"],
            "as_of": as_of,
            "ingested_at": now.isoformat(),
            "checked_at": now.isoformat(),
            "published_key": key,
        },
    )
    print(f"{cfg.source}: {doc['source_count']} sources catalogued -> {key}")
    return key

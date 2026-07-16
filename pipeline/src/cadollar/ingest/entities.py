"""Entity resolution: unify one organization across every lane.

Deterministic waterfall (per the spec):
  1. gather every organization mention across the published lanes, with the
     amount it carries and any strong identifier the source provides
  2. normalized name is the join key; strong IDs (EIN, CT#, UEI) attach as
     attributes
  3. a normalized name that collects two DIFFERENT EINs (or two UEIs) is
     flagged ambiguous and its identifiers withheld — never guessed
  4. publish one dossier per organization: its identifiers, its registry
     standing, and every lane it appears in with that lane's own amount

The dossier is the cross-source "follow the dollar" unit. Amounts are kept
per-lane and never summed — each lane measures a different thing.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

from ..config import REPO_ROOT, Settings
from ..publish.envelope import envelope
from ..sources import SourceConfig
from ..storage import Storage, read_manifest, write_manifest
from .csv_download import QualityGateError

# Legal-entity suffixes are stripped ONLY when they TRAIL the name (where they
# legally sit) — stripping "CO"/"COMPANY" anywhere would mangle "CO-OP" -> "OP"
# and merge "The Company Store" -> "The Store". Distinguishing words
# (FOUNDATION, UNIVERSITY, HOSPITAL, COUNTY...) are always kept.
_TRAIL_SUFFIX = {
    "INC", "INCORPORATED", "LLC", "CORP", "CORPORATION", "CO", "COMPANY",
    "LP", "LLP", "PC", "LTD", "PLLC",
}


def _norm(name: str) -> str:
    n = (name or "").upper()
    # drop everything after a DBA marker (the legal name is what precedes it)
    n = re.split(r"\bDBA\b", n)[0]
    for ch in (".", ",", "'", "’", "(", ")", "-", "/", "&"):
        n = n.replace(ch, " ")
    toks = n.split()
    # peel trailing legal suffixes iteratively; keep at least one token
    while len(toks) > 1 and toks[-1] in _TRAIL_SUFFIX:
        toks.pop()
    # drop a single leading article
    if len(toks) > 1 and toks[0] == "THE":
        toks = toks[1:]
    return " ".join(toks)


def _read(storage: Storage, key: str) -> dict | None:
    raw = storage.get_bytes(key)
    if raw is None:
        p = REPO_ROOT / "site" / "public" / "data" / key.removeprefix("published/")
        raw = p.read_bytes() if p.exists() else None
    return json.loads(raw) if raw else None


def _digits(s: str | None, width: int) -> str | None:
    d = re.sub(r"\D", "", s or "")
    return d if len(d) == width else None


def run_entities(storage: Storage, cfg: SourceConfig, settings: Settings) -> str:
    now = datetime.now(UTC)
    as_of = now.strftime("%Y-%m-%dT%H%M%SZ")
    manifest = read_manifest(storage, cfg.source)

    # entity -> accumulator
    ents: dict[str, dict[str, Any]] = {}

    def ent(name: str) -> dict[str, Any]:
        k = _norm(name)
        e = ents.get(k)
        if e is None:
            e = {
                "canonical_name": name.strip(),
                "eins": set(),
                "ueis": set(),
                "cts": set(),
                "aliases": set(),
                "appearances": {},
                "_namelen": len(name),
            }
            ents[k] = e
        # keep the longest surface form as the display name
        elif len(name) > e["_namelen"]:
            e["canonical_name"] = name.strip()
            e["_namelen"] = len(name)
        e["aliases"].add(name.strip())
        return e

    # --- checkbook vendors (name only) ---
    vp = _read(storage, "published/vendor_profiles.json")
    if vp:
        for name, p in vp["data"]["vendors"].items():
            if p.get("public_sector") or p.get("masked"):
                continue
            e = ent(name)
            e["appearances"]["checkbook"] = {
                "total_usd": p["total_usd"],
                "note": "state vendor payments, FY2020-25",
            }

    # --- grant recipients (name only) ---
    ga = _read(storage, "published/grants_awards.json")
    if ga:
        for r in ga["data"]["top_recipients"]:
            if (r.get("recipient_type") or "").strip().lower() == "public agency":
                continue
            e = ent(r["recipient_name"])
            e["appearances"]["grants"] = {
                "awarded_usd": r["awarded_usd"],
                "award_count": r["award_count"],
                "note": "state grant awards (AB 132)",
            }

    # --- BHCIP (name only) ---
    bh = _read(storage, "published/bhcip_awards.json")
    if bh:
        for o in bh["data"]["entities"]:
            e = ent(o["name"])
            e["appearances"]["bhcip"] = {
                "project_count": o["project_count"],
                "note": "behavioral-health infrastructure grants",
            }

    # --- federal recipients (UEI) ---
    fc = _read(storage, "published/federal_ca.json")
    if fc:
        for r in fc["data"]["recipients"]:
            if r.get("masked_aggregate"):
                continue
            e = ent(r["name"])
            if r.get("uei"):
                e["ueis"].add(r["uei"].strip().upper())
            e["appearances"]["federal_recipient"] = {
                "amount_usd": r["amount_usd"],
                "note": "federal awards performed in CA (FY2025)",
            }

    # --- FAC single audits (UEI) ---
    fa = _read(storage, "published/federal_audits.json")
    if fa:
        for a in fa["data"]["top_auditees"]:
            e = ent(a["name"])
            if a.get("uei"):
                e["ueis"].add(a["uei"].strip().upper())
            e["appearances"]["federal_audit"] = {
                "expended_usd": a["federal_expended_usd"],
                "entity_type": a.get("entity_type"),
                "report_id": a.get("report_id"),
                "note": f"audited federal spending (AY{fa['data']['audit_year']})",
            }

    # --- nonprofit registry + 990 (EIN, CT) — the identifier anchor ---
    np = _read(storage, "published/nonprofits.json")
    if np:
        for name, o in np["data"]["organizations"].items():
            e = ent(name)
            if (ein := _digits(o.get("fein"), 9)):
                e["eins"].add(ein)
            if o.get("ct_number"):
                e["cts"].add(o["ct_number"].strip())
            e["registry_status"] = o.get("registry_status")
            e["may_operate"] = o.get("may_operate")
            n990 = o.get("irs_990")
            if n990 and n990.get("total_revenue_usd") is not None:
                e["appearances"]["irs_990"] = {
                    "revenue_usd": n990["total_revenue_usd"],
                    "expenses_usd": n990.get("total_expenses_usd"),
                    "filing_year": n990.get("latest_filing_year"),
                    "url": n990.get("propublica_url"),
                    "note": "IRS Form 990 (whole organization, not just CA)",
                }

    doc = _finalize(ents)
    if doc["entity_count"] < cfg.min_rows:
        raise QualityGateError(f"{cfg.source}: only {doc['entity_count']} entities resolved")

    blob = json.dumps(doc, sort_keys=True, default=str).encode()
    content_hash = hashlib.sha256(blob).hexdigest()
    if manifest.get("content_hash") == content_hash:
        manifest["checked_at"] = now.isoformat()
        write_manifest(storage, cfg.source, manifest)
        print(f"{cfg.source}: unchanged, no-op")
        return manifest["published_key"]

    key = "published/entities.json"
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
            "row_count": doc["entity_count"],
            "as_of": as_of,
            "ingested_at": now.isoformat(),
            "checked_at": now.isoformat(),
            "published_key": key,
        },
    )
    print(
        f"{cfg.source}: {doc['entity_count']} entities, "
        f"{doc['multi_lane_count']} appearing in 2+ lanes -> {key}"
    )
    return key


def _finalize(ents: dict[str, dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, dict[str, Any]] = {}
    name_index: dict[str, str] = {}
    multi = 0
    ambiguous = 0
    id_anchored = 0
    for key, e in ents.items():
        eins, ueis, cts = e.pop("eins"), e.pop("ueis"), e.pop("cts")
        aliases = e.pop("aliases")
        e.pop("_namelen", None)
        # a name mapping to conflicting strong IDs is ambiguous: withhold the
        # IDs, flag it, still show the lane appearances
        conflict = len(eins) > 1 or len(ueis) > 1
        if conflict:
            ambiguous += 1
            e["ambiguous_identity"] = True
            e["ids"] = {}
        else:
            e["ids"] = {
                k: v
                for k, v in {
                    "ein": next(iter(eins), None),
                    "uei": next(iter(ueis), None),
                    "ct_number": next(iter(cts), None),
                }.items()
                if v
            }
        lanes = list(e["appearances"])
        e["lane_count"] = len(lanes)
        has_id = bool(e["ids"])
        if has_id:
            id_anchored += 1
        # confidence of the cross-source unification
        if len(lanes) <= 1 and not has_id:
            e["confidence"] = "single-source"
        elif has_id:
            e["confidence"] = "identifier-anchored"
        else:
            e["confidence"] = "name-matched"
        if e["lane_count"] >= 2:
            multi += 1
        # only publish entities worth a dossier: multi-lane OR carrying an ID
        if e["lane_count"] >= 2 or has_id:
            out[key] = e
            # case-insensitive exact-name lookup so the site never
            # re-implements normalization (checkbook names are UPPER, grant
            # names are Mixed — both must resolve)
            for alias in aliases:
                name_index[alias.upper()] = key

    return {
        "entity_count": len(out),
        "multi_lane_count": multi,
        "identifier_anchored_count": id_anchored,
        "ambiguous_count": ambiguous,
        "name_index": name_index,
        "entities": out,
    }

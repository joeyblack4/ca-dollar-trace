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
# "CO" (bare) is deliberately excluded: as a trailing token it would merge
# "Marin Co" -> "Marin" and collide with unrelated vendors. "COMPANY" (spelled
# out) is safe and kept.
_TRAIL_SUFFIX = {
    "INC", "INCORPORATED", "LLC", "CORP", "CORPORATION", "COMPANY",
    "LP", "LLP", "PC", "LTD", "PLLC",
}

# Stopwords that don't add specificity — used to judge whether a name is
# generic enough that a name-based merge could join two different organizations.
_STOPWORDS = {"OF", "THE", "AND", "FOR", "A", "IN", "CALIFORNIA", "CA"}


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
                # id value -> set of lanes that reported it (provenance): a
                # cross-source link is only identifier-CORROBORATED when the
                # same strong id is reported by >=2 lanes
                "ein_lanes": {},
                "uei_lanes": {},
                "cts": set(),
                "aliases": set(),
                "appearances": {},
                "_namelen": len(name),
                "_norm": k,
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
                e["uei_lanes"].setdefault(r["uei"].strip().upper(), set()).add(
                    "federal_recipient"
                )
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
                e["uei_lanes"].setdefault(a["uei"].strip().upper(), set()).add("federal_audit")
            e["appearances"]["federal_audit"] = {
                "expended_usd": a["federal_expended_usd"],
                "entity_type": a.get("entity_type"),
                "report_id": a.get("report_id"),
                "note": f"audited federal spending (AY{fa['data']['audit_year']})",
            }

    # --- hospital annual financials (name only) ---
    hf = _read(storage, "published/hospital_finances.json")
    if hf:
        fy = hf["data"]["headline_fy"]
        for h in hf["data"]["hospitals"].values():
            y = h["years"].get(fy)
            if not y:
                continue
            e = ent(h["name"])
            e["appearances"]["hospital"] = {
                "net_patient_rev_usd": y["net_patient_rev_usd"],
                "medical_usd": y["medical_ffs_usd"] + y["medical_managed_usd"],
                "note": f"hospital financial disclosure (FY{fy}, HCAI)",
            }

    # --- nonprofit registry + 990 (EIN, CT) — the identifier anchor ---
    np = _read(storage, "published/nonprofits.json")
    if np:
        for name, o in np["data"]["organizations"].items():
            e = ent(name)
            if (ein := _digits(o.get("fein"), 9)):
                e["ein_lanes"].setdefault(ein, set()).add("nonprofit_registry")
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
        ein_lanes, uei_lanes, cts = e.pop("ein_lanes"), e.pop("uei_lanes"), e.pop("cts")
        aliases = e.pop("aliases")
        norm = e.pop("_norm")
        e.pop("_namelen", None)
        lanes = list(e["appearances"])
        e["lane_count"] = len(lanes)

        # a name mapping to conflicting strong IDs (two EINs / two UEIs) is
        # ambiguous: withhold IDs, flag it, keep the lane appearances
        conflict = len(ein_lanes) > 1 or len(uei_lanes) > 1
        # a generic name (few distinctive tokens) can join two different orgs;
        # its identifiers are shown only with a caution
        significant = [t for t in norm.split() if t not in _STOPWORDS]
        generic = len(significant) < 3
        # a strong id is CORROBORATED when a single id value is reported by 2+
        # lanes — that is the only truly identifier-anchored cross-source link
        corroborated = any(len(ls) >= 2 for ls in ein_lanes.values()) or any(
            len(ls) >= 2 for ls in uei_lanes.values()
        )

        if conflict:
            ambiguous += 1
            e["ambiguous_identity"] = True
            e["ids"] = {}
        else:
            e["ids"] = {
                k: v
                for k, v in {
                    "ein": next(iter(ein_lanes), None),
                    "uei": next(iter(uei_lanes), None),
                    "ct_number": next(iter(cts), None),
                }.items()
                if v
            }
        has_id = bool(e["ids"])
        # a conflict withholds the IDs, so we can't claim a proven ID link even
        # if one value happened to repeat across lanes — fall back to name-matched
        if e["lane_count"] >= 2 and corroborated and not conflict:
            e["confidence"] = "identifier-linked"  # shared hard id across lanes
            id_anchored += 1
        elif e["lane_count"] >= 2:
            e["confidence"] = "name-matched"  # lanes joined by name only
        else:
            e["confidence"] = "single-source"
        # honest caveat: a generic name with an identifier attached might be
        # the wrong organization's identifier
        if generic and has_id and not corroborated and e["lane_count"] >= 2:
            e["identity_caution"] = (
                "This name may refer to more than one organization; identifiers "
                "shown are the best available match, not a proven link."
            )
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

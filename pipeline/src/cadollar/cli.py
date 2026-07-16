"""cadollar CLI.

  cadollar run grants_portal        # fetch -> raw -> cleansed -> published
  cadollar run ebudget_enacted
  cadollar run-all                  # every registered source (what cron calls)
  cadollar sync-site                # copy published/*.json -> site/public/data (local mode)
"""

from __future__ import annotations

import argparse
import shutil
import sys

from .config import REPO_ROOT, Settings, get_settings
from .ingest.bhcip import run_bhcip
from .ingest.city_checkbooks import run_city_checkbooks
from .ingest.county_finances import run_county_finances
from .ingest.csv_download import run_csv_ingest
from .ingest.ebudget import run_ebudget
from .ingest.ebudget_detail import run_ebudget_detail
from .ingest.fac_sefa import run_fac_sefa
from .ingest.fiscal_vendor import run_fiscal_vendor
from .ingest.grants_awards import run_grants_awards
from .ingest.medical_plans import run_medical_plans
from .ingest.sacs import run_sacs
from .ingest.usaspending import run_usaspending
from .publish.grants import publish_grants_summary
from .sources import load_source
from .storage import Storage, get_storage
from .transform import grants_portal as t_grants


def _run_grants(storage: Storage, settings: Settings) -> None:
    cfg = load_source(settings, "grants_portal")
    # publish runs INSIDE the ingest (before the manifest commits the new
    # content hash) so a publish failure is retried next run, not masked
    result = run_csv_ingest(
        storage, cfg, t_grants.cleanse, publish=lambda: publish_grants_summary(storage, cfg)
    )
    if result.changed:
        print(f"grants_portal: ingested {result.row_count} rows (as_of {result.as_of})")
    else:
        print("grants_portal: unchanged upstream, no-op")


def _run_ebudget(storage: Storage, settings: Settings) -> None:
    cfg = load_source(settings, "ebudget_enacted")
    run_ebudget(storage, cfg, settings)


def _run_ebudget_detail(storage: Storage, settings: Settings) -> None:
    cfg = load_source(settings, "ebudget_detail")
    run_ebudget_detail(storage, cfg, settings)


def _run_usaspending(storage: Storage, settings: Settings) -> None:
    cfg = load_source(settings, "usaspending_ca")
    run_usaspending(storage, cfg, settings)


def _run_fiscal_vendor(storage: Storage, settings: Settings) -> None:
    cfg = load_source(settings, "fiscal_vendor")
    run_fiscal_vendor(storage, cfg, settings)


def _run_grants_awards(storage: Storage, settings: Settings) -> None:
    cfg = load_source(settings, "grants_awards")
    run_grants_awards(storage, cfg, settings)


def _run_bhcip(storage: Storage, settings: Settings) -> None:
    cfg = load_source(settings, "bhcip_awards")
    run_bhcip(storage, cfg, settings)


def _run_medical_plans(storage: Storage, settings: Settings) -> None:
    cfg = load_source(settings, "medical_plans")
    run_medical_plans(storage, cfg, settings)


def _run_county_finances(storage: Storage, settings: Settings) -> None:
    cfg = load_source(settings, "county_finances")
    run_county_finances(storage, cfg, settings)


def _run_city_finances(storage: Storage, settings: Settings) -> None:
    cfg = load_source(settings, "city_finances")
    run_county_finances(storage, cfg, settings)  # same connector, city config


def _run_sacs(storage: Storage, settings: Settings) -> None:
    cfg = load_source(settings, "sacs_k12")
    run_sacs(storage, cfg, settings)


def _run_city_checkbooks(storage: Storage, settings: Settings) -> None:
    cfg = load_source(settings, "city_checkbooks")
    run_city_checkbooks(storage, cfg, settings)


def _run_fac_sefa(storage: Storage, settings: Settings) -> None:
    cfg = load_source(settings, "fac_sefa")
    run_fac_sefa(storage, cfg, settings)


RUNNERS = {
    "grants_portal": _run_grants,
    "ebudget_enacted": _run_ebudget,
    "ebudget_detail": _run_ebudget_detail,
    "usaspending_ca": _run_usaspending,
    "fiscal_vendor": _run_fiscal_vendor,
    "grants_awards": _run_grants_awards,
    "bhcip_awards": _run_bhcip,
    "medical_plans": _run_medical_plans,
    "county_finances": _run_county_finances,
    "city_finances": _run_city_finances,
    "sacs_k12": _run_sacs,
    "city_checkbooks": _run_city_checkbooks,
    "fac_sefa": _run_fac_sefa,
}

# multi-GB backfills that need a persistent data dir; run explicitly, not from cron
HEAVY = {"fiscal_vendor"}

# EXPLICIT execution order for run-all: ebudget_enacted must publish the
# waterfall before ebudget_detail cross-checks against it. (Alphabetical
# ordering would run detail first — that was a real bug.)
RUN_ORDER = [
    "ebudget_enacted",
    "ebudget_detail",
    "grants_portal",
    "grants_awards",
    "usaspending_ca",
    "bhcip_awards",
    "medical_plans",
    "county_finances",
    "city_finances",
    "sacs_k12",
    "city_checkbooks",
    "fac_sefa",
    "fiscal_vendor",
]
assert set(RUN_ORDER) == set(RUNNERS), "RUN_ORDER must list every runner exactly once"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cadollar")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run_p = sub.add_parser("run")
    run_p.add_argument("source", choices=sorted(RUNNERS))
    sub.add_parser("run-all")
    sub.add_parser("sync-site")
    args = parser.parse_args(argv)

    settings = get_settings()
    storage = get_storage(settings)

    if args.cmd == "sync-site":
        src = settings.data_dir / "published"
        dest = REPO_ROOT / "site" / "public" / "data"
        dest.mkdir(parents=True, exist_ok=True)
        copied = 0
        current = set()
        for f in sorted(src.rglob("*.json")):
            rel = f.relative_to(src)
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest / rel)
            current.add(rel)
            copied += 1
        # mirror semantics: prune site files no longer produced, so retired
        # outputs don't serve stale numbers forever — but never mass-delete
        # (a nearly-empty published/ dir means this run didn't produce much)
        stale = [f for f in dest.rglob("*.json") if f.relative_to(dest) not in current]
        if current and len(stale) <= max(3, len(current) // 4):
            for f in stale:
                f.unlink()
                print(f"pruned stale {f.relative_to(dest)}")
        elif stale:
            print(f"WARNING: {len(stale)} stale file(s) NOT pruned (safety cap); review manually")
        print(f"synced {copied} published file(s) -> {dest}")
        return 0

    sources = (
        [s for s in RUN_ORDER if s not in HEAVY] if args.cmd == "run-all" else [args.source]
    )
    failures: list[str] = []
    for source in sources:
        try:
            RUNNERS[source](storage, settings)
        except Exception as e:  # one failing source must not block the others
            if args.cmd != "run-all":
                raise
            failures.append(source)
            print(f"ERROR {source}: {e}", file=sys.stderr)
    if failures:
        print(f"run-all: {len(failures)} source(s) failed: {', '.join(failures)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

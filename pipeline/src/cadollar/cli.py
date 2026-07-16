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
from .ingest.csv_download import run_csv_ingest
from .ingest.ebudget import run_ebudget
from .ingest.ebudget_detail import run_ebudget_detail
from .ingest.usaspending import run_usaspending
from .publish.grants import publish_grants_summary
from .sources import load_source
from .storage import Storage, get_storage
from .transform import grants_portal as t_grants


def _run_grants(storage: Storage, settings: Settings) -> None:
    cfg = load_source(settings, "grants_portal")
    result = run_csv_ingest(storage, cfg, t_grants.cleanse)
    if result.changed:
        print(f"grants_portal: ingested {result.row_count} rows (as_of {result.as_of})")
        key = publish_grants_summary(storage, cfg)
        print(f"grants_portal: published {key}")
    else:
        print("grants_portal: unchanged upstream, no-op")


def _run_ebudget(storage: Storage, settings: Settings) -> None:
    cfg = load_source(settings, "ebudget_enacted")
    run_ebudget(storage, cfg, settings)


def _run_ebudget_detail(storage: Storage, settings: Settings) -> None:
    cfg = load_source(settings, "ebudget_detail")
    run_ebudget_detail(storage, cfg, settings)


# run-all executes in sorted order; ebudget_enacted sorts before ebudget_detail,
# which the detail cross-source check relies on.
def _run_usaspending(storage: Storage, settings: Settings) -> None:
    cfg = load_source(settings, "usaspending_ca")
    run_usaspending(storage, cfg, settings)


RUNNERS = {
    "grants_portal": _run_grants,
    "ebudget_enacted": _run_ebudget,
    "ebudget_detail": _run_ebudget_detail,
    "usaspending_ca": _run_usaspending,
}


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
        for f in sorted(src.rglob("*.json")):
            rel = f.relative_to(src)
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest / rel)
            copied += 1
        print(f"synced {copied} published file(s) -> {dest}")
        return 0

    sources = sorted(RUNNERS) if args.cmd == "run-all" else [args.source]
    for source in sources:
        RUNNERS[source](storage, settings)
    return 0


if __name__ == "__main__":
    sys.exit(main())

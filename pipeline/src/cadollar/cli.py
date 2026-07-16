"""cadollar CLI.

  cadollar ingest grants_portal      # fetch -> raw -> cleansed (change-detected)
  cadollar publish grants_portal     # cleansed -> published JSON
  cadollar run grants_portal         # ingest + publish (what cron calls)
  cadollar sync-site                 # copy published/*.json -> site/public/data (local mode)
"""

from __future__ import annotations

import argparse
import shutil
import sys

from .config import REPO_ROOT, get_settings
from .ingest.csv_download import run_csv_ingest
from .publish.grants import publish_grants_summary
from .sources import load_source
from .storage import get_storage
from .transform import grants_portal as t_grants

# Per-source wiring: (cleanse callable, publish callable)
REGISTRY = {
    "grants_portal": (t_grants.cleanse, publish_grants_summary),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cadollar")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for cmd in ("ingest", "publish", "run"):
        p = sub.add_parser(cmd)
        p.add_argument("source", choices=sorted(REGISTRY))
    sub.add_parser("sync-site")
    args = parser.parse_args(argv)

    settings = get_settings()
    storage = get_storage(settings)

    if args.cmd == "sync-site":
        src = settings.data_dir / "published"
        dest = REPO_ROOT / "site" / "public" / "data"
        dest.mkdir(parents=True, exist_ok=True)
        copied = 0
        for f in sorted(src.glob("*.json")):
            shutil.copy2(f, dest / f.name)
            copied += 1
        print(f"synced {copied} published file(s) -> {dest}")
        return 0

    cfg = load_source(settings, args.source)
    cleanse, publish = REGISTRY[args.source]

    if args.cmd in ("ingest", "run"):
        result = run_csv_ingest(storage, cfg, cleanse)
        if result.changed:
            print(f"{args.source}: ingested {result.row_count} rows (as_of {result.as_of})")
        else:
            print(f"{args.source}: unchanged upstream, no-op")
            if args.cmd == "run":
                return 0

    if args.cmd in ("publish", "run"):
        key = publish(storage, cfg)
        print(f"{args.source}: published {key}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

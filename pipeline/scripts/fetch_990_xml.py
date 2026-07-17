"""Capture IRS Form 990 e-file XMLs for the nonprofits the site tracks.

Everything comes from the IRS's official bulk e-file releases — no third-party
scraping. Flow:
  1. read the EINs from the published nonprofits.json
  2. download the IRS yearly index CSVs (EIN -> newest 990/990EZ object_id +
     the exact zip batch that contains it)
  3. download only the needed monthly zips, extract only our members into
     sources/captured/990/, delete each zip

The IRS zips use Deflate64, which stdlib zipfile can't decompress — run via:
  uv run --with inflate64 python scripts/fetch_990_xml.py [year ...]
Years default to the two most recent index years the IRS has posted. A member
missing from its indexed batch is retried against the batch's sibling zips
(the IRS re-batches: index may say 05A while the file sits in 05B).

Idempotent: already-extracted members are skipped, so re-runs only fetch new
filings. Re-run when the IRS posts new zips (monthly-ish, ~a year behind
filing) and then `cadollar run nonprofit_officers`.
"""

from __future__ import annotations

import csv
import io
import json
import re
import struct
import subprocess
import sys
import tempfile
import zipfile
from collections import defaultdict
from pathlib import Path

import inflate64

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "pipeline" / "sources" / "captured" / "990"
NONPROFITS = REPO / "site" / "public" / "data" / "nonprofits.json"
IRS = "https://apps.irs.gov/pub/epostcard/990/xml"


def curl(url: str, dest: Path | None = None) -> bytes | None:
    args = ["curl", "-sL", "--fail", "--max-time", "1800", url]
    if dest:
        r = subprocess.run(args + ["-o", str(dest)])
        return b"ok" if r.returncode == 0 else None
    r = subprocess.run(args, capture_output=True)
    return r.stdout if r.returncode == 0 else None


def read_member(z: zipfile.ZipFile, name: str) -> bytes:
    info = z.getinfo(name)
    if info.compress_type != 9:
        return z.read(name)
    f = z.fp
    assert f is not None
    f.seek(info.header_offset)
    hdr = f.read(30)
    if hdr[:4] != b"PK\x03\x04":
        raise ValueError(f"bad local header for {name}")
    n, m = struct.unpack("<HH", hdr[26:30])
    f.seek(info.header_offset + 30 + n + m)
    return inflate64.Inflater().inflate(f.read(info.compress_size))


def main(years: list[int]) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    orgs = json.loads(NONPROFITS.read_text())["data"]["organizations"]
    eins = {re.sub(r"\D", "", o.get("fein") or "") for o in orgs.values()}
    eins = {e for e in eins if len(e) == 9}
    print(f"{len(eins)} EINs to look for; index years {years}")

    # newest 990/990EZ per EIN across the index years
    best: dict[str, tuple[str, str, str]] = {}  # ein -> (tax_period+rank, object_id, batch)
    for yr in years:
        raw = curl(f"{IRS}/{yr}/index_{yr}.csv")
        if raw is None:
            print(f"index_{yr}.csv not posted yet, skipping")
            continue
        for row in csv.DictReader(io.StringIO(raw.decode("utf-8", "replace"))):
            ein = (row.get("EIN") or "").strip()
            rt = (row.get("RETURN_TYPE") or "").strip()
            if ein not in eins or rt not in ("990", "990EZ"):
                continue
            rank = f"{(row.get('TAX_PERIOD') or '').strip()}:{1 if rt == '990' else 0}"
            if ein not in best or rank > best[ein][0]:
                best[ein] = (rank, row["OBJECT_ID"].strip(), row["XML_BATCH_ID"].strip())

    by_batch: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for ein, (_, oid, batch) in best.items():
        if not (OUT / f"{ein}_{oid}_public.xml").exists():
            by_batch[batch].append((ein, oid))
    print(f"{len(best)} filings matched; {sum(map(len, by_batch.values()))} to fetch "
          f"across {len(by_batch)} zips")

    leftovers: list[tuple[str, str, str]] = []  # (batch, ein, oid) not in indexed zip
    with tempfile.TemporaryDirectory() as td:
        def extract_from(batch: str, members: list[tuple[str, str]]) -> list[tuple[str, str]]:
            zpath = Path(td) / f"{batch}.zip"
            for cand in (batch, batch.upper()):
                if curl(f"{IRS}/{batch[:4]}/{cand}.zip", zpath):
                    break
            else:
                print(f"{batch}: download failed")
                return members
            missed = []
            try:
                with zipfile.ZipFile(zpath) as z:
                    names = {n.rsplit("/", 1)[-1]: n for n in z.namelist()}
                    for ein, oid in members:
                        mem = names.get(f"{oid}_public.xml")
                        if mem is None:
                            missed.append((ein, oid))
                            continue
                        (OUT / f"{ein}_{oid}_public.xml").write_bytes(read_member(z, mem))
            finally:
                zpath.unlink(missing_ok=True)
            print(f"{batch}: extracted {len(members) - len(missed)}/{len(members)}")
            return missed

        for batch, members in sorted(by_batch.items()):
            for ein, oid in extract_from(batch, members):
                leftovers.append((batch, ein, oid))

        # IRS re-batches: retry misses against sibling zips (05A -> 05B, 05C...)
        retry: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for batch, ein, oid in leftovers:
            for suffix in "ABCD":
                sib = batch[:-1] + suffix
                if sib != batch:
                    retry[sib].append((ein, oid))
                    break  # one sibling guess per round; rerun script for more
        for batch, members in sorted(retry.items()):
            extract_from(batch, members)

    have = len(list(OUT.glob("*_public.xml")))
    print(f"captured XMLs on disk: {have}")
    return 0 if have else 1


if __name__ == "__main__":
    yrs = [int(a) for a in sys.argv[1:]] or [2024, 2025, 2026]
    sys.exit(main(yrs))

# CA Dollar Trace

Follow your California tax dollar — and see exactly where the trail goes dark.

Every number on the site is cited to its government source with an as-of date, a
coverage flag (`traceable` / `category_only` / `trail_ends_here` / `masked`), and a
one-click link to the raw data. Where public visibility ends, we say so: **a gap is
never rendered as a zero.**

## Architecture (batch-first, near-zero-ops)

```
GitHub Actions cron ──> pipeline (Python/DuckDB) ──> parquet layers + published JSON
                                                          │
                        Next.js static export  <──────────┘
                        on Cloudflare Workers (Static Assets)
```

- **`pipeline/`** — Python 3.12 (`uv`), package `cadollar`. Declarative YAML source
  configs (`pipeline/sources/*.yaml`), httpx+stamina fetch with change-detection,
  DuckDB cleansing to typed parquet (raw → cleansed → curated), fail-honest quality
  gates, and published JSON with a mandatory provenance envelope.
- **`site/`** — Next.js (App Router, `output: "export"`), Tailwind 4. Deployed as
  Cloudflare Workers Static Assets from `site/wrangler.jsonc`.
- **Scheduling** — GitHub Actions cron (`.github/workflows/ingest-daily.yml`). Data
  changes are committed (provenance history for free) and auto-deploy on push.
- **No servers, no database.** Pipeline state lives in per-source manifests; storage
  is local parquet in dev and Cloudflare R2 (S3 API) in prod when the interactive
  drill-down layer (DuckDB-WASM over parquet) lands.

## Develop

```bash
# pipeline
cd pipeline
uv sync
uv run pytest
uv run cadollar run grants_portal   # fetch -> cleanse -> publish (local mode)
uv run cadollar sync-site           # copy published JSON into site/public/data

# site
cd site
npm install
npm run dev
```

## Deploy

Site: push to `main` (Cloudflare Workers Builds), or manually:

```bash
cd site && npm run build && npx wrangler deploy
```

## Data sources

| Source | Cadence | Status |
|---|---|---|
| ebudget enacted summary (GF sankey + agency statistics) | budget cycle | ✅ live |
| ebudget department detail (230 depts × programs + funds) | budget cycle | ✅ live |
| [California Grants Portal](https://data.ca.gov/dataset/california-grants-portal) | daily | ✅ live |
| USAspending federal-into-CA recipients | monthly-ish | ✅ live |
| Open FI$Cal vendor transactions | monthly (60-day lag) | ⚠️ CAPTCHA-gated (see /gaps) |
| SCO ByTheNumbers | annual | planned (Phase 1) |
| SACS / Ed-Data | annual | planned (Phase 1) |

Per-source caveats live in `pipeline/sources/*.yaml` and render on every figure.

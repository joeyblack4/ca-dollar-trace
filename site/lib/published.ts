/* Build-time loader for pipeline-published JSON (synced into public/data/).
   Static export renders these at build; the raw JSON also ships at /data/*.json
   so every figure has a one-click "Get the data" link. */

import { promises as fs } from "fs";
import path from "path";

export interface SourceInfo {
  name: string;
  publisher: string;
  url: string;
  license: string;
}

export type CoverageFlag = "traceable" | "category_only" | "trail_ends_here" | "masked";

export interface Published<T> {
  source: SourceInfo;
  as_of: string;
  ingested_at: string;
  cadence: string;
  coverage_flag: CoverageFlag;
  caveats: string[];
  data: T;
}

export interface GrantsStatusTotal {
  status: string;
  grant_count: number;
  est_avail_funds_known_usd: number | null;
  funds_unknown_count: number;
}

export interface GrantsCategoryRow {
  category: string;
  grant_count: number;
  est_avail_funds_known_usd: number | null;
  funds_unknown_count: number;
}

export interface GrantsSummary {
  totals_by_status: GrantsStatusTotal[];
  open_by_category: GrantsCategoryRow[];
}

export async function loadPublished<T>(name: string): Promise<Published<T>> {
  const file = path.join(process.cwd(), "public", "data", `${name}.json`);
  return JSON.parse(await fs.readFile(file, "utf-8")) as Published<T>;
}

export function fmtUsd(n: number | null): string {
  if (n === null) return "unknown";
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `$${(n / 1e3).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
}

export function fmtAsOf(asOf: string): string {
  // "2026-07-16T024321Z" -> "2026-07-16"
  return asOf.slice(0, 10);
}

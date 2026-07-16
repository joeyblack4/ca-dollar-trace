/* Shared types + formatters for pipeline-published JSON.
   (Client-safe: the fs-based build-time loader lives in published-server.ts.) */

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

export interface FlowItem {
  name: string;
  usd: number;
}

export interface DownstreamHop {
  label: string;
  flag: CoverageFlag;
  note: string;
  cite: string;
}

export interface DownstreamNode {
  node: string;
  hops: DownstreamHop[];
}

export interface AgencyRow {
  org_cd: string;
  title: string;
  state_funds_usd: number;
  all_funds_usd: number;
  general_fund_usd: number;
  special_fund_usd: number;
  bond_fund_usd: number;
  positions: number;
}

export interface BudgetWaterfall {
  budget_year: string;
  basis: string;
  general_fund: {
    revenue: FlowItem[];
    expenditure: FlowItem[];
    revenue_total_usd: number;
    expenditure_total_usd: number;
    gap_usd: number;
  };
  agencies: AgencyRow[];
  state_grand_total_usd: number;
  downstream_visibility: DownstreamNode[];
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

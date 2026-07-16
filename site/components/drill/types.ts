import type { VendorDept } from "@/components/agency/VendorsSection";
import type { AgencyDetail } from "@/lib/agency";
import type { Published } from "@/lib/published";

export type PathSeg =
  | { kind: "area"; name: string }
  | { kind: "agency"; cd: string }
  | { kind: "dept"; orgCd: string }
  | { kind: "checkbook"; orgCd: string }
  | { kind: "vendor"; name: string }
  | { kind: "recovered"; program: string }
  | { kind: "plans" };

export interface MedicalPlansDoc {
  latest_month: string;
  total_enrollees: number;
  plan_count: number;
  plans: {
    plan_name: string;
    plan_type: string | null;
    enrollees: number | null;
    county_count: number;
    suppressed_county_rows: number;
    capitation: {
      rate_year: number;
      pmpm_range: [number, number];
      rate_cells: number;
      name_match: string;
    } | null;
  }[];
  plans_with_capitation_match: number;
  enrollee_weighted_match_pct: number | null;
}

export interface BhcipDoc {
  project_count: number;
  entity_count: number;
  by_round: { round: string; project_count: number }[];
  entities: { name: string; project_count: number; projects: { project: string; round: string }[] }[];
  administrator_vendor_names: string[];
}

export interface VendorProfile {
  total_usd: number;
  masked: boolean;
  public_sector: boolean;
  years: Record<string, number>;
  /** gross positives, present only for years with material adjustments */
  years_gross?: Record<string, number>;
  departments: { org_cd: string; title: string; agency_cd: string | null; usd: number }[];
  programs: { program: string; usd: number }[];
}

export type AgencyDoc = Published<AgencyDetail>;
export type VendorsDoc = Published<{ departments: VendorDept[] }>;
export type ProfilesDoc = Published<{ vendors: Record<string, VendorProfile> }>;

import type { VendorDept } from "@/components/agency/VendorsSection";
import type { AgencyDetail } from "@/lib/agency";
import type { Published } from "@/lib/published";

export type PathSeg =
  | { kind: "area"; name: string }
  | { kind: "agency"; cd: string }
  | { kind: "dept"; orgCd: string }
  | { kind: "checkbook"; orgCd: string }
  | { kind: "vendor"; name: string }
  | { kind: "recovered"; program: string };

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
  departments: { org_cd: string; title: string; agency_cd: string | null; usd: number }[];
  programs: { program: string; usd: number }[];
}

export type AgencyDoc = Published<AgencyDetail>;
export type VendorsDoc = Published<{ departments: VendorDept[] }>;
export type ProfilesDoc = Published<{ vendors: Record<string, VendorProfile> }>;

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
  | { kind: "plans" }
  | { kind: "hospitals" }
  | { kind: "counties" }
  | { kind: "districts" };

export interface SearchIndexDoc {
  vendor_count: number;
  dossier_count: number;
  vendors: {
    name: string;
    total_usd: number;
    area: string;
    agency_cd: string;
    dept_org_cd: string;
    dossier: boolean;
  }[];
}

export interface NonprofitsDoc {
  organizations: Record<
    string,
    {
      registered_name: string;
      registry_status: string;
      ct_number: string;
      may_operate: boolean;
      irs_990?: {
        propublica_url: string;
        latest_filing_year: number | null;
        total_revenue_usd: number | null;
      } | null;
    }
  >;
}

export interface HospitalFinancesDoc {
  headline_fy: string;
  hospital_count: number;
  years: Record<
    string,
    {
      hospital_count: number;
      audited_count: number;
      in_process_count: number;
      net_patient_rev_usd: number;
      medical_ffs_usd: number;
      medical_managed_usd: number;
      medicare_usd: number;
    }
  >;
  name_index: Record<string, string>;
  hospitals: Record<
    string,
    {
      name: string;
      county: string | null;
      control: string | null;
      care_type: string | null;
      years: Record<
        string,
        {
          report_status: string | null;
          net_patient_rev_usd: number;
          medical_ffs_usd: number;
          medical_managed_usd: number;
          medicare_usd: number;
          county_usd: number;
          commercial_usd: number;
          operating_expenses_usd: number;
          salaries_usd: number;
          net_income_usd: number;
        }
      >;
    }
  >;
}

export interface NonprofitOfficersDoc {
  org_count: number;
  officer_count: number;
  name_index: Record<string, string>;
  organizations: Record<
    string,
    {
      registry_name: string | null;
      tax_year: number | null;
      people_reported: number;
      paid_count: number;
      officers: {
        name: string;
        title: string;
        org_comp_usd: number;
        related_comp_usd: number;
        other_comp_usd: number;
        total_comp_usd: number;
      }[];
    }
  >;
}

export interface CompensationDoc {
  year: number;
  state_by_org_cd: Record<
    string,
    { employer: string; positions: number; wages_usd: number; benefits_usd: number }
  >;
}

export interface EntitiesDoc {
  name_index: Record<string, string>;
  entities: Record<
    string,
    {
      canonical_name: string;
      ids: { ein?: string; uei?: string; ct_number?: string };
      registry_status?: string;
      may_operate?: boolean;
      lane_count: number;
      confidence: string;
      ambiguous_identity?: boolean;
      identity_caution?: string;
      appearances: Record<
        string,
        {
          note: string;
          total_usd?: number;
          awarded_usd?: number;
          award_count?: number;
          project_count?: number;
          amount_usd?: number;
          expended_usd?: number;
          medical_usd?: number;
          net_patient_rev_usd?: number;
          revenue_usd?: number;
          entity_type?: string;
          url?: string;
        }
      >;
    }
  >;
}

export interface K12ApportionmentDoc {
  fiscal_year: string;
  certification: string;
  lea_count: number;
  statewide_total_usd: number;
  leas: Record<
    string,
    {
      name: string;
      lea_type: string | null;
      is_charter: boolean;
      total_apportionment_usd: number;
      lcff_state_aid_epa_usd: number;
      epa_usd: number;
      special_ed_usd: number;
    }
  >;
}

export interface K12CompDoc {
  year: number;
  district_count: number;
  positions: number;
  wages_usd: number;
  benefits_usd: number;
  fallback_year?: number;
  fallback_district_count?: number;
  statewide_titles: {
    title: string;
    positions: number;
    median_pay_usd: number;
    max_pay_usd: number;
  }[];
  districts: Record<
    string,
    {
      name: string;
      year: number;
      positions: number;
      wages_usd: number;
      benefits_usd: number;
      title_count: number;
      titles: {
        title: string;
        positions: number;
        median_pay_usd: number;
        max_pay_usd: number;
        median_benefits_usd: number;
      }[];
    }
  >;
}

export interface K12Doc {
  fiscal_year: string;
  lea_count: number;
  statewide_spend_usd: number;
  statewide_by_class: { object_class: string; usd: number }[];
  districts_published: number;
  districts_not_shown: number;
  districts_not_shown_spend_usd: number;
  district_names_unmatched: number;
  districts: {
    cds: string;
    district: string | null;
    county: string | null;
    spend_usd: number | null;
    revenue_usd: number | null;
    unparsed: number;
    spend_by_class: { object_class: string; usd: number }[];
  }[];
}

export interface CountyFinancesDoc {
  county_count: number;
  not_in_this_dataset: string[];
  latest_fiscal_year: number;
  counties_lagging_behind_latest_fy: string[];
  total_latest_usd: number;
  counties: {
    county: string;
    fiscal_year: number;
    total_usd: number | null;
    population: number | null;
    per_capita_usd: number | null;
    top_categories: { category: string; usd: number }[];
    category_count: number;
    amount_unparsed_count: number;
  }[];
}

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

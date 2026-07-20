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
  | { kind: "districts" }
  // revenue tree (left side of the Sankey): rooted at a revenue source bar
  | { kind: "revenue"; name: string }
  | { kind: "rev_migration" }
  | { kind: "rev_brackets" }
  | { kind: "rev_counties" }
  | { kind: "rev_county"; county: string }
  | { kind: "rev_zips"; county: string }
  | { kind: "rev_high_income" }
  | { kind: "rev_industries" }
  | { kind: "rev_income_classes" }
  | { kind: "rev_companies" }
  | { kind: "rev_biztypes" }
  | { kind: "rev_cities" };

/* ---------- revenue drill docs (published/revenue/*) ---------- */

export interface BudgetReference {
  budget_year: string;
  waterfall_usd: number;
  stats_total_usd: number;
  note: string;
}

export interface PitBracket {
  label: string;
  floor_usd: number | null; // null = negative or zero AGI
  ceiling_usd: number | null; // null = open-ended top band
  returns: number;
  agi_usd: number;
  tax_liability_usd: number;
  avg_tax_usd: number;
  share_of_tax_pct: number;
  cum_share_of_tax_pct: number; // this band and above
  share_of_returns_pct: number;
}

export interface PitHighIncomeTier {
  label: string;
  floor_usd: number;
  returns: number;
  tax_liability_usd: number;
  share_of_tax_pct: number;
}

export interface PitCountyBracket {
  label: string;
  returns: number | null; // null = suppressed at source, never zero
  agi_usd: number | null;
  tax_assessed_usd: number | null;
}

export interface PitCounty {
  county: string;
  returns: number;
  agi_usd: number;
  tax_assessed_usd: number;
  per_return_tax_usd: number;
  brackets: PitCountyBracket[];
  suppressed_cells: number;
}

export interface DisplayBand {
  label: string;
  returns: number;
  share_of_returns_pct: number;
  share_of_tax_pct: number;
}

export interface BandComposition {
  source: string;
  usd: number;
  returns: number;
  share_of_income_pct: number;
}

export interface BandOverlays {
  seniors: number;
  renters_credit: number;
  dependents_credit: number;
  self_employed: number;
  amt: number;
  mental_health_tax: number;
  mental_health_tax_usd: number;
}

export interface PitRevenueDoc {
  tax_year: number;
  budget_reference: BudgetReference;
  statewide: { returns: number; agi_usd: number; tax_liability_usd: number };
  brackets: PitBracket[];
  display_bands: (DisplayBand & {
    tax_liability_usd: number;
    avg_tax_usd: number;
    composition: BandComposition[];
    itemized_income_usd: number;
    total_income_usd: number;
    overlays: BandOverlays;
  })[];
  high_income: PitHighIncomeTier[];
  counties: PitCounty[];
  non_geographic: { label: string; returns: number; tax_assessed_usd: number }[];
  county_tax_year: number;
  county_measure_note: string;
  county_cross_check: {
    state_totals_usd: number;
    counties_sum_usd: number;
    suppression_residual_usd: number;
  };
  zip_tax_year: number;
  zip_coverage: { counties: number; zips: number; listed_total_tax_usd: number; note: string };
}

export interface PitZipDoc {
  county: string;
  tax_year: number;
  total_tax_liability_usd: number;
  zips: {
    zip: string;
    city: string;
    returns: number | null;
    agi_usd: number | null;
    tax_liability_usd: number;
  }[];
}

export interface CorpIndustry {
  industry: string;
  returns: number | null;
  net_income_usd: number | null;
  tax_liability_usd: number;
  share_of_tax_pct: number;
  c_corp_tax_usd: number | null;
  s_corp_tax_usd: number | null;
}

export interface CorpIncomeClass {
  label: string;
  returns: number | null;
  net_income_usd: number | null;
  tax_assessed_usd: number;
  share_of_tax_pct: number;
}

export interface CorpRevenueDoc {
  tax_year: number;
  budget_reference: BudgetReference;
  statewide: {
    returns_with_liability: number;
    net_income_usd: number;
    tax_liability_usd: number;
  };
  industries: CorpIndustry[];
  industry_reconciliation: { leaf_sum_usd: number; file_total_usd: number };
  income_classes: CorpIncomeClass[];
  display_classes: (DisplayBand & { tax_assessed_usd: number })[];
  income_class_tax_year: number;
  income_class_measure_note: string;
  income_class_total_usd: number;
}

export interface CorpPublicCompany {
  company: string;
  cik: number;
  ticker: string | null;
  hq_state: string | null;
  ca_hq: boolean;
  state_local_tax_expense_usd: number;
  total_income_tax_expense_usd: number | null;
}

export interface CorpPublicCompaniesDoc {
  calendar_year: number;
  companies: CorpPublicCompany[];
  universe: {
    companies_reporting: number;
    excluded_implausible: number;
    shown: number;
    screen_rule: string;
  };
  measure_note: string;
}

export interface SalesRevenueDoc {
  latest_quarter: string;
  trailing_quarters: string[];
  budget_reference: BudgetReference;
  fund_split_fiscal_year: string;
  fund_split: { fund: string; revenue_usd: number }[];
  business_types: {
    label: string;
    naics: string;
    taxable_sales_usd: number;
    permits: number | null;
    share_pct: number;
  }[];
  business_type_reconciliation: { partition_sum_usd: number; total_all_outlets_usd: number };
  counties: { county: string; taxable_sales_usd: number; suppressed: boolean }[];
  county_reconciliation: { counties_sum_usd: number; statewide_total_usd: number };
  cities: {
    city: string;
    county: string;
    taxable_sales_usd: number | null;
    suppressed: boolean;
  }[];
  suppressed_city_count: number;
  base_note: string;
}

export interface InsuranceRevenueDoc {
  assessment_year: number;
  business_year: number | null;
  budget_reference: BudgetReference;
  types: { type: string; businesses: number | null; assessed_usd: number; share_pct: number }[];
  net_adjustments_usd: number;
  reconciliation: { leaf_sum_usd: number; totals_usd: number; grand_totals_usd: number };
}

/* Federal lens: IRS statistics on the same Californians — age (60+ flag),
   filing status, migration. Rendered ONLY in badged federal-lens panels. */
export interface FederalLensClass {
  label: string;
  returns: number;
  elderly_returns: number;
  elderly_pct: number;
  single: number;
  joint: number;
  head_of_household: number;
  other_status: number;
  agi_usd: number;
}

export interface FederalMigrationFlow {
  label: string;
  inflow_returns: number;
  outflow_returns: number;
  net_returns: number;
  inflow_agi_usd: number;
  outflow_agi_usd: number;
}

export interface FederalLensDoc {
  framing: string;
  tax_year: number;
  statewide_by_class: FederalLensClass[];
  statewide_totals: { irs_returns: number; ftb_returns: number; ratio: number; note: string };
  counties: {
    county: string;
    returns: number;
    elderly_returns: number;
    elderly_pct: number;
    classes: FederalLensClass[];
    correspondence: { irs_returns: number; ftb_returns: number | null; ratio: number | null };
  }[];
  migration: {
    years: string;
    inflow_returns: number;
    outflow_returns: number;
    net_returns: number;
    inflow_agi_usd: number;
    outflow_agi_usd: number;
    net_agi_usd: number;
    by_income: FederalMigrationFlow[];
    by_age: FederalMigrationFlow[];
    trend: {
      years: string;
      inflow_returns: number;
      outflow_returns: number;
      net_returns: number;
      inflow_agi_usd: number;
      outflow_agi_usd: number;
      net_agi_usd: number;
    }[];
    trend_note: string;
  };
}

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

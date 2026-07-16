/* Types for the per-agency drill-down documents (published/agencies/{cd}.json) */

export interface ProgramLine {
  program_code: string | null;
  title: string;
  usd: number;
  positions: number | null;
}

export interface DepartmentDetail {
  org_cd: string;
  title: string;
  total_usd: number;
  general_fund_usd: number;
  positions: number | null;
  programs: ProgramLine[];
  funds_by_class: Record<string, number>;
  integrity: {
    program_lines_sum_usd?: number;
    matches_department_total?: boolean;
    no_program_detail_published?: boolean;
  };
}

export interface AgencyDetail {
  agency_cd: string;
  title: string;
  total_usd: number;
  summary_cross_check: { summary_all_funds_usd: number; drift_pct: number };
  departments: DepartmentDetail[];
}

/** Sankey program-area name -> agency page code (where a 1:1 page exists) */
export const AGENCY_PAGE_FOR_NODE: Record<string, string> = {
  "Health and Human Services": "4000",
  "K-12 Education": "6010",
  "Higher Education": "6013",
  "Corrections and Rehabilitation": "5210",
};

export const metadata = { title: "How to read these numbers — CA Dollar Trace" };

/* The reconciliation / datasheet page: what each headline figure is on, why
   figures from different sources don't add up, and the honest limits. This is
   the "don't sum these" guardrail made explicit. */

interface Figure {
  label: string;
  value: string;
  basis: string;
  year: string;
  scope: string;
}

const FIGURES: Figure[] = [
  {
    label: "State budget (General Fund + all funds)",
    value: "$228.4B GF / $321.1B all funds",
    basis: "Enacted budget — what the Legislature appropriated (budgetary/legal basis)",
    year: "2025-26",
    scope: "Planned spending, not actual cash out the door",
  },
  {
    label: "State checkbook (Open FI$Cal vendor payments)",
    value: "~$76B/year",
    basis: "Actual payment transactions, net of reversals (modified accrual)",
    year: "FY2024-25 complete; FY2025-26 in progress",
    scope: "~79% of expenditures; excludes payroll, bulk benefits, confidential vendors",
  },
  {
    label: "Government payroll",
    value: "$169.6B wages + $52.7B benefits",
    basis: "Compensation reported to the State Controller (2.3M positions, by job title)",
    year: "2024 (a district that filed only 2023 is shown as 2023)",
    scope:
      "State, county, city, K-12, UC/CSU/community-college, special-district & court employees; the checkbook's biggest exclusion. Some districts never file — their payroll shows as absent, not zero",
  },
  {
    label: "Medi-Cal managed care",
    value: "13.8M enrollees; capitation rate ranges",
    basis: "Enrollment counts + certified per-member-per-month rate ranges (prices)",
    year: "June 2026 enrollment; 2024-26 rates",
    scope: "Rates are prices, not dollars spent; plan-to-provider payments are not public",
  },
  {
    label: "K-12 school districts",
    value: "$112.1B",
    basis: "Unaudited actuals, self-reported by ~2,000 LEAs",
    year: "FY2024-25",
    scope: "General Fund operating only; excludes construction funds & transfers (they double-count)",
  },
  {
    label: "Counties / cities / special districts",
    value: "$126.3B / $115.8B / $102.4B",
    basis: "Financial Transactions Reports, self-reported, posted as submitted (not audited)",
    year: "FY2023-24",
    scope: "Category level; no vendor detail except LA & SF checkbooks",
  },
  {
    label: "Federal single audits (FAC)",
    value: "$254.9B",
    basis: "Total federal awards expended per each entity's audited SEFA",
    year: "AY2024",
    scope: "Entities spending $750k+/$1M+ in federal money; includes the State's own $159B",
  },
  {
    label: "Federal awards into California (USAspending)",
    value: "top recipients + subaward hand-offs",
    basis: "Award obligations for work performed in CA",
    year: "FY2025",
    scope: "Obligations, not outlays; subaward reporting is incomplete below $30k",
  },
];

export default function MethodologyPage() {
  return (
    <div>
      <h1 className="text-3xl font-semibold tracking-tight">How to read these numbers</h1>
      <p className="mt-3 max-w-2xl text-fog">
        Every figure on this site is real and cited — but they come from different systems, on
        different accounting bases, for different years. The single most important rule:{" "}
        <strong className="text-ink">
          you cannot add numbers from different sources together
        </strong>
        . A budget appropriation, an actual payment, a salary, and audited federal spending each
        measure a different thing. Here is what each headline figure actually is.
      </p>

      <div className="mt-8 overflow-x-auto">
        <table className="w-full min-w-[720px] text-sm">
          <thead>
            <tr className="border-b border-rule text-left align-bottom text-fog">
              <th className="py-2 pr-4 font-medium">Figure</th>
              <th className="py-2 pr-4 font-medium">What it is (basis)</th>
              <th className="py-2 pr-4 font-medium">Year</th>
              <th className="py-2 font-medium">Scope &amp; caveat</th>
            </tr>
          </thead>
          <tbody>
            {FIGURES.map((f) => (
              <tr key={f.label} className="border-b border-rule/60 align-top">
                <td className="py-3 pr-4">
                  <div className="font-medium">{f.label}</div>
                  <div className="font-mono text-xs text-fog">{f.value}</div>
                </td>
                <td className="py-3 pr-4 text-fog">{f.basis}</td>
                <td className="py-3 pr-4 font-mono text-xs text-fog">{f.year}</td>
                <td className="py-3 text-fog">{f.scope}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <section className="mt-10 max-w-2xl space-y-4 text-sm text-fog">
        <div>
          <h2 className="text-lg font-semibold text-ink">Why they don&apos;t add up</h2>
          <p className="mt-1">
            The same dollar can appear in several of these. Federal money into California shows up
            in the state budget (as federal funds), in a department&apos;s spending, in the single
            audit, and in USAspending — that&apos;s one flow seen four ways, not four separate
            pots. Summing them would count it four times.
          </p>
        </div>
        <div>
          <h2 className="text-lg font-semibold text-ink">Self-reported vs. audited</h2>
          <p className="mt-1">
            County, city, district, and K-12 figures are reported by those governments to the
            State Controller and posted as submitted — not independently audited. We flag this on
            every such figure. The single-audit data (FAC) is the exception: it&apos;s the product
            of an independent audit.
          </p>
        </div>
        <div>
          <h2 className="text-lg font-semibold text-ink">How organizations are linked</h2>
          <p className="mt-1">
            When one organization appears in several lanes, we unify it by name and attach any
            strong identifier a source publishes (federal UEI, IRS EIN, charity registration
            number). We only call a cross-source link{" "}
            <strong className="text-ink">identifier-linked</strong> when the{" "}
            <em>same</em> strong identifier is reported by two or more independent lanes — that is
            the one case a link is truly proven. Everything else is labeled{" "}
            <strong className="text-ink">name-matched</strong>: joined by name alone, which is our
            best guess, not a certainty. When a name is common enough that it could belong to more
            than one organization, we say so on the record itself. And a name that maps to two
            different identifiers is left unlinked rather than guessed.
          </p>
        </div>
        <div>
          <h2 className="text-lg font-semibold text-ink">Where the record simply ends</h2>
          <p className="mt-1">
            Some money can&apos;t be followed further in any public data — Medi-Cal
            plan-to-provider payments, most county and school-district vendors, spending through
            the tax code. Those aren&apos;t omissions; they&apos;re labeled dead ends. See the{" "}
            <a href="/gaps/" className="underline underline-offset-2 hover:text-ink">
              dark zones
            </a>
            .
          </p>
        </div>
      </section>
    </div>
  );
}

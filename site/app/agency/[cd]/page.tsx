import { promises as fs } from "fs";
import path from "path";
import Link from "next/link";
import { CoverageMeter } from "@/components/ui/CoverageMeter";
import { DepartmentsTable } from "@/components/agency/DepartmentsTable";
import { SourceChip } from "@/components/ui/SourceChip";
import { loadPublished } from "@/lib/published-server";
import { fmtUsd, type BudgetWaterfall, type Published } from "@/lib/published";
import type { AgencyDetail } from "@/lib/agency";

async function agencyCodes(): Promise<string[]> {
  const dir = path.join(process.cwd(), "public", "data", "agencies");
  return (await fs.readdir(dir)).filter((f) => f.endsWith(".json")).map((f) => f.replace(".json", ""));
}

export async function generateStaticParams() {
  return (await agencyCodes()).map((cd) => ({ cd }));
}

export async function generateMetadata({ params }: { params: Promise<{ cd: string }> }) {
  const { cd } = await params;
  const pub = await loadPublished<AgencyDetail>(`agencies/${cd}`);
  return { title: `${pub.data.title} — CA Dollar Trace` };
}

export default async function AgencyPage({ params }: { params: Promise<{ cd: string }> }) {
  const { cd } = await params;
  const pub = await loadPublished<AgencyDetail>(`agencies/${cd}`);
  const waterfall = await loadPublished<BudgetWaterfall>("budget_waterfall");
  const agency = pub.data;
  const downstream = waterfall.data.downstream_visibility.find((d) =>
    agency.title.includes(d.node) || d.node.includes(agency.title.replace(" thru ", "-"))
  );

  const programCount = agency.departments.reduce((n, d) => n + d.programs.length, 0);

  return (
    <div>
      <nav className="text-sm text-fog">
        <Link href="/" className="underline underline-offset-2 hover:text-ink">
          Budget waterfall
        </Link>{" "}
        / <Link href="/explore/" className="underline underline-offset-2 hover:text-ink">agencies</Link> /{" "}
        {agency.title}
      </nav>

      <h1 className="mt-3 text-3xl font-semibold tracking-tight">{agency.title}</h1>
      <p className="mt-2 max-w-2xl text-fog">
        {fmtUsd(agency.total_usd)} enacted for {waterfall.data.budget_year} across{" "}
        {agency.departments.length} departments and {programCount} budget programs. Detail sums
        reconcile with the DOF summary (drift {agency.summary_cross_check.drift_pct}%).
      </p>

      <div className="mt-6">
        <CoverageMeter
          levels={[
            {
              label: "Budget bucket",
              ok: true,
              note: "Agency totals from the enacted budget.",
            },
            {
              label: "Departments",
              ok: true,
              note: `${agency.departments.length} departments with fund splits.`,
            },
            {
              label: "Programs",
              ok: true,
              note: `${programCount} program lines, integrity-checked.`,
            },
            {
              label: "Payments to vendors",
              ok: false,
              note: "The state checkbook (Open FI$Cal) gates every download behind a CAPTCHA — no machine access.",
              href: "/gaps/#fiscal-captcha",
            },
          ]}
        />
      </div>

      <h2 className="mt-10 text-xl font-semibold">Departments</h2>
      <p className="mt-1 text-sm text-fog">
        Click a department to unfold its fund mix and program lines.
      </p>
      <DepartmentsTable departments={agency.departments} />

      {downstream && (
        <section className="mt-10">
          <h2 className="text-xl font-semibold">
            Where this money goes next — and where we lose sight of it
          </h2>
          <ol className="mt-3 grid gap-3 sm:grid-cols-2">
            {downstream.hops.map((hop, i) => (
              <li
                key={hop.label}
                className={
                  hop.flag === "trail_ends_here"
                    ? "rounded-md border border-dark-zone/40 p-3 text-sm [background-image:repeating-linear-gradient(45deg,transparent,transparent_6px,rgba(87,83,78,0.06)_6px,rgba(87,83,78,0.06)_12px)]"
                    : "rounded-md border border-rule p-3 text-sm"
                }
              >
                <div className="font-mono text-xs text-fog">hop {i + 1}</div>
                <div className="mt-0.5 font-medium">{hop.label}</div>
                <p className="mt-1 text-fog">{hop.note}</p>
                <a
                  href={hop.cite}
                  className="mt-1 inline-block text-xs underline decoration-rule underline-offset-2 hover:text-ink"
                >
                  source ↗
                </a>
              </li>
            ))}
          </ol>
        </section>
      )}

      <SourceChip
        source={pub.source}
        asOf={pub.as_of}
        cadence={pub.cadence}
        coverage={pub.coverage_flag}
        caveats={pub.caveats}
        dataHref={`/data/agencies/${cd}.json`}
      />
    </div>
  );
}

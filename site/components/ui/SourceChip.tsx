/* Datawrapper-style provenance chip: source name + link, as-of stamp,
   coverage badge, expandable caveats, and a "Get the data" link.
   Every figure on the site sits above one of these. */

import { cn } from "@/lib/cn";
import { CoverageFlag, SourceInfo, fmtAsOf } from "@/lib/published";

const COVERAGE_LABEL: Record<CoverageFlag, string> = {
  traceable: "Traceable",
  category_only: "Category-level only",
  trail_ends_here: "Trail ends here",
  masked: "Masked by statute",
};

const COVERAGE_STYLE: Record<CoverageFlag, string> = {
  traceable: "bg-traceable/10 text-traceable border-traceable/30",
  category_only: "bg-category-only/10 text-category-only border-category-only/30",
  trail_ends_here: "bg-dark-zone/10 text-dark-zone border-dark-zone/40 [background-image:repeating-linear-gradient(45deg,transparent,transparent_4px,rgba(87,83,78,0.08)_4px,rgba(87,83,78,0.08)_8px)]",
  masked: "bg-dark-zone/10 text-dark-zone border-dark-zone/30",
};

export function CoverageBadge({ flag }: { flag: CoverageFlag }) {
  return (
    <span
      className={cn(
        "inline-block rounded-full border px-2 py-0.5 text-xs font-medium",
        COVERAGE_STYLE[flag]
      )}
    >
      {COVERAGE_LABEL[flag]}
    </span>
  );
}

export function SourceChip({
  source,
  asOf,
  cadence,
  coverage,
  caveats,
  dataHref,
}: {
  source: SourceInfo;
  asOf: string;
  cadence: string;
  coverage: CoverageFlag;
  caveats: string[];
  dataHref?: string;
}) {
  return (
    <div className="mt-4 border-t border-rule pt-3 text-sm text-fog">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span>
          Source:{" "}
          <a href={source.url} className="underline decoration-rule underline-offset-2 hover:text-ink">
            {source.name}
          </a>{" "}
          ({source.publisher})
        </span>
        <span className="font-mono text-xs">as of {fmtAsOf(asOf)}</span>
        <span className="text-xs">{cadence}</span>
        <CoverageBadge flag={coverage} />
        {dataHref && (
          <a href={dataHref} className="text-xs underline decoration-rule underline-offset-2 hover:text-ink">
            Get the data
          </a>
        )}
      </div>
      {caveats.length > 0 && (
        <details className="mt-1">
          <summary className="cursor-pointer text-xs hover:text-ink">
            Caveats ({caveats.length})
          </summary>
          <ul className="mt-1 list-disc pl-5 text-xs">
            {caveats.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </details>
      )}
      <p className="mt-1 text-xs">
        License: {source.license} · Processed by CA Dollar Trace
      </p>
    </div>
  );
}

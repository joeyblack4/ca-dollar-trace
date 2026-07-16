/* The coverage meter: how far down can we actually trace this money?
   Levels are computed from what data exists, not asserted. The broken level
   links to the gap registry entry explaining why and what would fix it. */

import { cn } from "@/lib/cn";

export interface CoverageLevel {
  label: string;
  ok: boolean;
  note: string;
  href?: string;
}

export function CoverageMeter({ levels }: { levels: CoverageLevel[] }) {
  return (
    <div className="rounded-lg border border-rule p-4">
      <div className="text-sm font-medium">How far can we trace this money?</div>
      <ol className="mt-3 flex flex-col gap-2 sm:flex-row sm:gap-0">
        {levels.map((lvl, i) => (
          <li key={lvl.label} className="flex-1">
            <div className="flex items-center">
              <div
                className={cn(
                  "h-2 w-full",
                  i === 0 && "rounded-l-full",
                  i === levels.length - 1 && "rounded-r-full",
                  lvl.ok
                    ? "bg-traceable"
                    : "bg-dark-zone/30 [background-image:repeating-linear-gradient(45deg,transparent,transparent_3px,rgba(87,83,78,0.35)_3px,rgba(87,83,78,0.35)_6px)]"
                )}
              />
            </div>
            <div className="mt-1.5 pr-3 text-xs">
              <span className={cn("font-medium", lvl.ok ? "text-traceable" : "text-dark-zone")}>
                {lvl.ok ? "✓" : "✕"} {lvl.label}
              </span>
              <p className="mt-0.5 text-fog">
                {lvl.note}
                {lvl.href && (
                  <>
                    {" "}
                    <a href={lvl.href} className="underline underline-offset-2 hover:text-ink">
                      why?
                    </a>
                  </>
                )}
              </p>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

"use client";

/* One continuous surface: the Sankey seeds the drill path, the explorer
   expands below it, level by level, on the same page. */

import { useState } from "react";
import { BudgetSankey } from "@/components/viz/BudgetSankey";
import { AGENCY_PAGE_FOR_NODE } from "@/lib/agency";
import type { BudgetWaterfall } from "@/lib/published";
import { DrillExplorer } from "./DrillExplorer";
import { VendorSearch } from "./VendorSearch";
import type { PathSeg } from "./types";

export function ExplorerShell({
  waterfall,
  asOfLabel,
}: {
  waterfall: BudgetWaterfall;
  asOfLabel: string;
}) {
  const [path, setPath] = useState<PathSeg[]>([]);

  const onDrill = (areaName: string) => {
    const cd = AGENCY_PAGE_FOR_NODE[areaName];
    setPath(
      cd
        ? [{ kind: "area", name: areaName }, { kind: "agency", cd }]
        : [{ kind: "area", name: areaName }]
    );
  };

  return (
    <div>
      <div className="mb-5">
        <VendorSearch onJump={setPath} />
        <p className="mt-1.5 px-1 text-xs text-fog">
          Know who you&apos;re looking for? Jump straight to any organization the state pays — or
          click through the budget below.
        </p>
      </div>
      <BudgetSankey data={waterfall} asOfLabel={asOfLabel} onDrill={onDrill} />
      <DrillExplorer waterfall={waterfall} path={path} setPath={setPath} />
    </div>
  );
}

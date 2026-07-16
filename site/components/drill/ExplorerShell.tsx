"use client";

/* One continuous surface: the Sankey seeds the drill path, the explorer
   expands below it, level by level, on the same page. */

import { useState } from "react";
import { BudgetSankey } from "@/components/viz/BudgetSankey";
import { AGENCY_PAGE_FOR_NODE } from "@/lib/agency";
import type { BudgetWaterfall } from "@/lib/published";
import { DrillExplorer } from "./DrillExplorer";
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
      <BudgetSankey data={waterfall} asOfLabel={asOfLabel} onDrill={onDrill} />
      <DrillExplorer waterfall={waterfall} path={path} setPath={setPath} />
    </div>
  );
}

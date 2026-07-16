"use client";

/* Interactive General Fund waterfall (Sankey):
   revenue sources -> General Fund -> program areas.

   - Revenue flows: blue #2a78d6; spending flows: poppy #e87722 (pair validated:
     CVD dE 110; poppy is sub-3:1 on paper so every node is direct-labeled and a
     table view exists on the page — the relief rule).
   - The enacted plan spends more than it raises; the difference arrives as a
     visually distinct striped gray "Reserves & carryover" band, never hidden.
   - Click a node for the detail panel: amount, share, cents-of-every-$1, and
     the downstream visibility trail with coverage flags. */

import { useMemo, useState } from "react";
import {
  sankey,
  sankeyJustify,
  sankeyLinkHorizontal,
  type SankeyLink,
  type SankeyNode,
} from "d3-sankey";
import { cn } from "@/lib/cn";
import { CoverageBadge } from "@/components/ui/SourceChip";
import { AGENCY_PAGE_FOR_NODE } from "@/lib/agency";
import { fmtUsd, type BudgetWaterfall, type DownstreamNode } from "@/lib/published";

const REVENUE = "#2a78d6";
const SPENDING = "#e87722";
const RESERVES = "#8a8781";

type Side = "revenue" | "gf" | "spending" | "reserves";

interface NodeDatum {
  id: string; // side-prefixed — "Other" exists on BOTH sides (revenue & spending)
  name: string;
  side: Side;
}
type LinkDatum = { derived?: boolean };
type N = SankeyNode<NodeDatum, LinkDatum>;
type L = SankeyLink<NodeDatum, LinkDatum>;

const W = 960;
const H = 480;
const GF = "General Fund";

/* SVG-label-only shortenings; the detail panel always shows the full source name */
const DISPLAY_NAME: Record<string, string> = {
  "Transfer from the Budget Stabilization Account/Rainy Day Fund": "Rainy Day Fund transfer",
};
const displayName = (name: string) => DISPLAY_NAME[name] ?? name;

export function BudgetSankey({
  data,
  asOfLabel,
  onDrill,
}: {
  data: BudgetWaterfall;
  asOfLabel: string;
  onDrill?: (areaName: string) => void;
}) {
  const [selected, setSelected] = useState<string>(`gf:${GF}`);
  const [hovered, setHovered] = useState<string | null>(null);

  const { nodes, links } = useMemo(() => {
    const gf = data.general_fund;
    const nodeList: NodeDatum[] = [
      ...gf.revenue.map((r) => ({ id: `rev:${r.name}`, name: r.name, side: "revenue" as Side })),
      { id: "reserves", name: "Reserves & carryover", side: "reserves" as Side },
      { id: `gf:${GF}`, name: GF, side: "gf" as Side },
      ...gf.expenditure.map((e) => ({ id: `exp:${e.name}`, name: e.name, side: "spending" as Side })),
    ];
    const idx = new Map(nodeList.map((n, i) => [n.id, i]));
    const linkList = [
      ...gf.revenue.map((r) => ({
        source: idx.get(`rev:${r.name}`)!,
        target: idx.get(`gf:${GF}`)!,
        value: r.usd,
      })),
      {
        source: idx.get("reserves")!,
        target: idx.get(`gf:${GF}`)!,
        value: gf.gap_usd,
        derived: true,
      },
      ...gf.expenditure.map((e) => ({
        source: idx.get(`gf:${GF}`)!,
        target: idx.get(`exp:${e.name}`)!,
        value: e.usd,
      })),
    ];
    // horizontal insets leave gutters for the direct labels beside edge nodes
    const layout = sankey<NodeDatum, LinkDatum>()
      .nodeWidth(14)
      .nodePadding(14)
      .nodeAlign(sankeyJustify)
      .extent([
        [210, 20],
        [W - 235, H - 18],
      ]);
    return layout({
      nodes: nodeList.map((n) => ({ ...n })),
      links: linkList.map((l) => ({ ...l })),
    });
  }, [data]);

  const linkPath = sankeyLinkHorizontal<NodeDatum, LinkDatum>();

  const detail = buildDetail(selected, data);

  return (
    <div>
      <div className="overflow-x-auto rounded-lg border border-rule bg-white/40 p-4">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="min-w-[760px]"
          role="img"
          aria-label={`California General Fund ${data.budget_year} enacted budget: revenue sources flowing into the General Fund and out to program areas`}
        >
          <defs>
            {/* striped band for the derived reserves/deficit flow */}
            <pattern id="stripes" patternUnits="userSpaceOnUse" width="8" height="8" patternTransform="rotate(45)">
              <rect width="8" height="8" fill={RESERVES} opacity="0.25" />
              <line x1="0" y1="0" x2="0" y2="8" stroke={RESERVES} strokeWidth="4" opacity="0.45" />
            </pattern>
          </defs>

          {(links as L[]).map((l, i) => {
            const src = l.source as N;
            const tgt = l.target as N;
            const active =
              hovered === null || hovered === src.id || hovered === tgt.id;
            return (
              <path
                key={i}
                d={linkPath(l) ?? undefined}
                fill="none"
                stroke={
                  l.derived
                    ? "url(#stripes)"
                    : src.side === "gf"
                      ? SPENDING
                      : REVENUE
                }
                strokeWidth={Math.max(1, l.width ?? 1)}
                strokeOpacity={l.derived ? 1 : active ? 0.45 : 0.12}
                className="transition-[stroke-opacity] duration-150"
              />
            );
          })}

          {(nodes as N[]).map((n) => {
            const h = (n.y1 ?? 0) - (n.y0 ?? 0);
            const isLeft = n.side === "revenue" || n.side === "reserves";
            const isGf = n.side === "gf";
            const usd = n.value ?? 0;
            const nodeSelected = selected === n.id;
            return (
              <g
                key={n.id}
                onClick={() => {
                  setSelected(n.id);
                  if (onDrill && n.side === "spending") onDrill(n.name);
                }}
                onMouseEnter={() => setHovered(n.id)}
                onMouseLeave={() => setHovered(null)}
                className="cursor-pointer"
              >
                {/* generous hit target */}
                <rect
                  x={(n.x0 ?? 0) - 6}
                  y={(n.y0 ?? 0) - 4}
                  width={(n.x1 ?? 0) - (n.x0 ?? 0) + 12}
                  height={h + 8}
                  fill="transparent"
                />
                <rect
                  x={n.x0}
                  y={n.y0}
                  width={(n.x1 ?? 0) - (n.x0 ?? 0)}
                  height={h}
                  rx={3}
                  fill={
                    n.side === "reserves"
                      ? RESERVES
                      : n.side === "spending"
                        ? SPENDING
                        : n.side === "gf"
                          ? "#1a1916"
                          : REVENUE
                  }
                  stroke={nodeSelected ? "#1a1916" : "transparent"}
                  strokeWidth={2}
                />
                {/* direct labels: name + value (relief rule) */}
                <text
                  x={isGf ? ((n.x0 ?? 0) + (n.x1 ?? 0)) / 2 : isLeft ? (n.x0 ?? 0) - 10 : (n.x1 ?? 0) + 10}
                  y={isGf ? (n.y0 ?? 0) - 14 : ((n.y0 ?? 0) + (n.y1 ?? 0)) / 2}
                  textAnchor={isGf ? "middle" : isLeft ? "end" : "start"}
                  dominantBaseline={isGf ? "auto" : "central"}
                  className="fill-ink text-[13px] font-medium"
                >
                  {displayName(n.name)}
                  {isGf ? ` — ${fmtUsd(data.general_fund.expenditure_total_usd)} out` : ""}
                </text>
                {!isGf && (
                  <text
                    x={isLeft ? (n.x0 ?? 0) - 10 : (n.x1 ?? 0) + 10}
                    y={((n.y0 ?? 0) + (n.y1 ?? 0)) / 2 + 15}
                    textAnchor={isLeft ? "end" : "start"}
                    dominantBaseline="central"
                    className="fill-fog text-[11px]"
                  >
                    {fmtUsd(usd)}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      </div>

      <p className="mt-2 text-xs text-fog">
        General Fund only, {data.budget_year} enacted ({asOfLabel}). The striped band is
        derived: enacted spending exceeds revenues by {fmtUsd(data.general_fund.gap_usd)},
        covered by reserves and carryover — shown, not hidden. Click any block to trace it.
      </p>

      {detail && <DetailPanel detail={detail} inPageDrill={!!onDrill} />}
    </div>
  );
}

/* ---------- detail panel ---------- */

interface Detail {
  title: string;
  amountUsd: number;
  lines: string[];
  centsPerDollar?: number;
  downstream?: DownstreamNode;
  linkToGrants?: boolean;
  drillHref?: string;
  drillLabel?: string;
}

function buildDetail(id: string, data: BudgetWaterfall): Detail | null {
  const gf = data.general_fund;
  if (id === `gf:${GF}`) {
    return {
      title: "General Fund",
      amountUsd: gf.expenditure_total_usd,
      lines: [
        `Revenues ${fmtUsd(gf.revenue_total_usd)} + reserves/carryover ${fmtUsd(gf.gap_usd)} → spending ${fmtUsd(gf.expenditure_total_usd)}.`,
        "The General Fund is the state's discretionary checkbook. Special funds, bond funds, and federal passthroughs are additional — see the all-funds table below.",
      ],
    };
  }
  if (id === "reserves") {
    return {
      title: "Reserves & carryover (derived)",
      amountUsd: gf.gap_usd,
      lines: [
        "Derived figure: the gap between enacted General Fund spending and estimated revenues. It is covered by budget reserves (including the Rainy Day Fund) and fund balance carried over from prior years.",
        "We compute this from the two DOF totals rather than taking it from any single published field — flagged so you know it's our arithmetic, not a state line item.",
      ],
    };
  }
  const rev = gf.revenue.find((r) => `rev:${r.name}` === id);
  if (rev) {
    return {
      title: rev.name,
      amountUsd: rev.usd,
      lines: [
        `${((rev.usd / gf.revenue_total_usd) * 100).toFixed(1)}% of General Fund revenues.`,
      ],
      centsPerDollar: (rev.usd / gf.revenue_total_usd) * 100,
    };
  }
  const exp = gf.expenditure.find((e) => `exp:${e.name}` === id);
  if (exp) {
    const agencyCd = AGENCY_PAGE_FOR_NODE[exp.name];
    return {
      title: exp.name,
      amountUsd: exp.usd,
      lines: [`${((exp.usd / gf.expenditure_total_usd) * 100).toFixed(1)}% of General Fund spending.`],
      centsPerDollar: (exp.usd / gf.expenditure_total_usd) * 100,
      downstream: data.downstream_visibility.find((d) => d.node === exp.name),
      linkToGrants: exp.name === "Other",
      drillHref: agencyCd ? `/agency/${agencyCd}/` : "/explore/",
      drillLabel: agencyCd
        ? `Drill into departments, programs & fund mix →`
        : `Browse all twelve agencies →`,
    };
  }
  return null;
}

function DetailPanel({ detail, inPageDrill }: { detail: Detail; inPageDrill?: boolean }) {
  return (
    <div className="mt-4 rounded-lg border border-rule p-5">
      <div className="flex flex-wrap items-baseline gap-x-3">
        <h3 className="text-lg font-semibold">{detail.title}</h3>
        <span className="font-mono text-sm">{fmtUsd(detail.amountUsd)}</span>
        {detail.centsPerDollar !== undefined && (
          <span className="text-sm text-fog">
            {detail.centsPerDollar.toFixed(0)}¢ of every General Fund dollar
          </span>
        )}
      </div>
      {detail.lines.map((line) => (
        <p key={line} className="mt-2 max-w-3xl text-sm text-fog">
          {line}
        </p>
      ))}

      {detail.drillHref && (
        <p className="mt-3">
          <a
            href={inPageDrill ? "#drill" : detail.drillHref}
            className="inline-block rounded-md bg-poppy px-3 py-1.5 text-sm font-medium text-white hover:bg-poppy-deep"
          >
            {inPageDrill ? "Follow this money ↓" : detail.drillLabel}
          </a>
        </p>
      )}

      {detail.downstream && (
        <div className="mt-4">
          <h4 className="text-sm font-medium">Where this dollar goes next — and where we lose sight of it</h4>
          <ol className="mt-2 space-y-3">
            {detail.downstream.hops.map((hop, i) => (
              <li
                key={hop.label}
                className={cn(
                  "rounded-md border p-3 text-sm",
                  hop.flag === "trail_ends_here"
                    ? "border-dark-zone/40 [background-image:repeating-linear-gradient(45deg,transparent,transparent_6px,rgba(87,83,78,0.06)_6px,rgba(87,83,78,0.06)_12px)]"
                    : "border-rule"
                )}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs text-fog">hop {i + 1}</span>
                  <span className="font-medium">{hop.label}</span>
                  <CoverageBadge flag={hop.flag} />
                </div>
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
        </div>
      )}

      {detail.linkToGrants && (
        <p className="mt-3 text-sm">
          <a href="/grants/" className="text-poppy underline underline-offset-2 hover:text-poppy-deep">
            Explore live grant-program data →
          </a>
        </p>
      )}
    </div>
  );
}

// Recharts visualisations. Every chart degrades to an honest empty state
// when the backend has no records to plot.

import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { BarChart3 } from "lucide-react";
import type { Finding } from "../types";
import { EmptyState } from "./ui";
import { groupByMonth, humanize } from "../lib/geo";

const AXIS_TICK = { fill: "#64748B", fontSize: 11, fontFamily: "IBM Plex Mono" } as const;
const TOOLTIP_STYLE = {
  background: "#FFFFFF",
  border: "1px solid #E2E8F0",
  borderRadius: 10,
  fontSize: 12,
  color: "#0F172A",
  boxShadow: "0 8px 24px rgba(15,23,42,0.12)",
} as const;
const GRID_COLOR = "#E2E8F0";
const PRIMARY = "#0E7490";
const SECONDARY = "#3B82F6";

function ChartEmpty({ title, hint }: { title: string; hint?: string }) {
  return <EmptyState compact title={title} hint={hint} icon={<BarChart3 size={18} strokeWidth={1.5} />} />;
}

/** Horizontal bar: findings grouped by category. */
export function FindingsByCategoryChart({
  findings,
  emptyTitle = "No findings published yet — run an analysis.",
}: {
  findings: Finding[];
  emptyTitle?: string;
}) {
  const counts = new Map<string, number>();
  for (const f of findings) counts.set(f.category, (counts.get(f.category) ?? 0) + 1);
  const data = [...counts.entries()]
    .map(([category, count]) => ({ category: humanize(category), count }))
    .sort((a, b) => b.count - a.count);

  if (data.length === 0) {
    return <ChartEmpty title={emptyTitle} hint="Counts appear here once findings exist." />;
  }

  return (
    <ResponsiveContainer width="100%" height={Math.max(150, data.length * 24 + 30)}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, bottom: 4, left: 4 }}>
        <CartesianGrid horizontal={false} stroke={GRID_COLOR} strokeDasharray="3 3" />
        <XAxis type="number" tick={AXIS_TICK} stroke={GRID_COLOR} allowDecimals={false} />
        <YAxis
          type="category"
          dataKey="category"
          tick={AXIS_TICK}
          stroke={GRID_COLOR}
          width={148}
        />
        <Tooltip
          cursor={{ fill: "rgba(14,116,144,0.06)" }}
          contentStyle={TOOLTIP_STYLE}
          labelStyle={{ color: "#64748B" }}
          itemStyle={{ color: PRIMARY }}
        />
        <Bar dataKey="count" name="findings" fill={PRIMARY} barSize={12} radius={[0, 5, 5, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

/** Vertical bar: per-agent execution runtime (ms). */
export function AgentRuntimeChart({
  runs,
  emptyTitle = "No agent executions recorded yet.",
}: {
  runs: { name: string; ms: number }[];
  emptyTitle?: string;
}) {
  const data = runs
    .filter((r) => Number.isFinite(r.ms) && r.ms > 0)
    .map((r) => ({ name: r.name, seconds: Math.round((r.ms / 1000) * 100) / 100 }))
    .sort((a, b) => b.seconds - a.seconds);

  if (data.length === 0) {
    return (
      <ChartEmpty
        title={emptyTitle}
        hint="Durations are plotted from completed agent runs."
      />
    );
  }

  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: -8 }}>
        <CartesianGrid stroke={GRID_COLOR} strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="name" tick={AXIS_TICK} stroke={GRID_COLOR} interval={0} angle={-18} textAnchor="end" height={48} />
        <YAxis tick={AXIS_TICK} stroke={GRID_COLOR} width={44} />
        <Tooltip
          cursor={{ fill: "rgba(14,116,144,0.06)" }}
          contentStyle={TOOLTIP_STYLE}
          labelStyle={{ color: "#64748B" }}
          itemStyle={{ color: SECONDARY }}
          formatter={(value) => [`${value} s`, "runtime"]}
        />
        <Bar dataKey="seconds" name="runtime" fill={SECONDARY} barSize={16} radius={[5, 5, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

/** Line: findings created per month. */
export function FindingsOverTimeChart({
  findings,
  emptyTitle = "No findings yet — no time series to plot.",
}: {
  findings: Finding[];
  emptyTitle?: string;
}) {
  const data = groupByMonth(findings.map((f) => f.created_at));

  if (data.length === 0) {
    return (
      <div className="p-2">
        <ChartEmpty
          title={emptyTitle}
          hint="Monthly counts are computed from findings returned by the API."
        />
      </div>
    );
  }

  return (
    <div className="p-2">
      <ResponsiveContainer width="100%" height={240}>
        <LineChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: -8 }}>
          <CartesianGrid stroke={GRID_COLOR} strokeDasharray="3 3" />
          <XAxis dataKey="month" tick={AXIS_TICK} stroke={GRID_COLOR} />
          <YAxis tick={AXIS_TICK} stroke={GRID_COLOR} width={40} allowDecimals={false} />
          <Tooltip
            contentStyle={TOOLTIP_STYLE}
            labelStyle={{ color: "#64748B" }}
            itemStyle={{ color: PRIMARY }}
          />
          <Line
            type="monotone"
            dataKey="count"
            name="findings"
            stroke={PRIMARY}
            strokeWidth={2}
            dot={{ r: 3, fill: PRIMARY, strokeWidth: 1, stroke: "#FFFFFF" }}
            activeDot={{ r: 4 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

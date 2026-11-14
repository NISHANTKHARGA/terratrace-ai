// `/agents` — all twelve specialist agents, shown simply.
// Each agent is shown with its name, status, and one short description.

import { Link } from "react-router-dom";
import { Activity } from "lucide-react";
import { useApi } from "../services/api";
import { Badge, EmptyState, ErrorBanner, PanelLoading } from "../components/ui";
import { agentStatusTone } from "../lib/status";
import type { AgentSummary } from "../types";

function shortDescription(agent: AgentSummary): string {
  const text = agent.purpose.trim();
  const firstSentence = text.split(". ")[0]?.trim() ?? text;
  return firstSentence.endsWith(".") ? firstSentence : `${firstSentence}.`;
}

export default function AgentsPage() {
  const agents = useApi<{ items: AgentSummary[] }>("/api/agents");
  const items = agents.data?.items ?? [];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
            <Activity size={20} className="text-accent" /> Agents
          </h1>
          <p className="mt-1 text-sm text-muted">All twelve specialist agents, with a short description of what each one does.</p>
        </div>
        <div className="flex items-center gap-2">
          <Badge tone="muted">{items.length} / 12</Badge>
          <button className="btn" onClick={agents.refetch}>Refresh</button>
        </div>
      </div>

      {agents.error && <ErrorBanner message={agents.error} onRetry={agents.refetch} />}

      {agents.loading && !agents.data && (
        <section className="panel">
          <PanelLoading label="Loading agents…" />
        </section>
      )}

      {!agents.loading && !agents.error && items.length === 0 && (
        <section className="panel">
          <EmptyState
            title="No agents are registered yet."
            hint="The backend has not returned any agent records."
          />
        </section>
      )}

      {items.length > 0 && (
        <section className="panel overflow-hidden">
          <ul className="divide-y divide-line/70">
            {items.map((agent) => (
              <li key={agent.id}>
                <Link
                  to={`/agents/${agent.id}`}
                  className="flex items-start justify-between gap-4 px-5 py-4 transition hover:bg-raised/60"
                >
                  <div className="min-w-0">
                    <h2 className="text-[15px] font-medium leading-6">
                      {String(agent.ordinal).padStart(2, "0")} · {agent.name}
                    </h2>
                    <p className="mt-1 max-w-3xl text-sm leading-6 text-muted">
                      {shortDescription(agent)}
                    </p>
                  </div>
                  <Badge tone={agentStatusTone(agent.status)}>{agent.status}</Badge>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      {items.length > 0 && items.length < 12 && (
        <p className="text-sm text-amber">
          The backend returned {items.length} of 12 expected agents.
        </p>
      )}
    </div>
  );
}

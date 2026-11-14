// `/training` — Training Center: honest status of all 12 agents' training.

import { useState } from "react";
import { Loader2, Play, RefreshCw, CheckCircle2 } from "lucide-react";
import { api, useApi } from "../services/api";
import { Badge, EmptyState, ErrorBanner, type Tone } from "../components/ui";
import { AGENTS } from "../lib/agents";

const STATUS_TONE: Record<string, Tone> = {
  "Not Started": "muted",
  "Discovering Data": "accent",
  "Downloading Data": "accent",
  "Preparing Data": "accent",
  "Awaiting Labels": "amber",
  "Ready to Train": "steel2",
  "Training": "accent",
  "Evaluating": "steel2",
  "Trained": "success",
  "Deployed": "success",
  "Failed": "danger",
};

export default function TrainingPage() {
  const overview = useApi<any>("/api/training/overview", { pollMs: 0 });
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  async function run(action: () => Promise<any>, label: string) {
    setBusy(label);
    setMsg(null);
    try {
      const r = await action();
      setMsg(`${label}: ${r?.status ?? r?.note ?? "done"}`);
      overview.refetch();
    } catch (e) {
      setMsg(`${label} failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(null);
    }
  }

  const data = overview.data;
  const agents = data?.agents ?? [];
  const hardware = data?.hardware ?? {};

  return (
    <div className="mx-auto w-full max-w-[1180px] flex-1 px-4 py-6 sm:px-6">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-[18px] font-semibold tracking-tight text-paper">Training Center</h1>
          <p className="mt-0.5 text-[12.5px] text-muted">
            Real training infrastructure. An agent is "Trained" only when a real checkpoint exists.
          </p>
        </div>
        <button className="btn" onClick={() => overview.refetch()} disabled={overview.loading}>
          <RefreshCw size={13} className={overview.loading ? "animate-spin" : ""} /> Refresh
        </button>
      </div>

      {overview.error && <ErrorBanner message={overview.error} onRetry={overview.refetch} className="mt-4" />}

      {/* hardware */}
      <div className="mt-4 rounded-2xl border border-line bg-white p-4 shadow-card">
        <h2 className="label mb-2">Hardware</h2>
        <p className="text-[12.5px] text-paper">
          GPU: {hardware.gpu_available ? `${hardware.gpu_name} (${hardware.gpu_memory_gb} GB)` : "none (CPU fallback)"}
          {" · "}PyTorch {hardware.torch_version ?? "—"}
          {" · "}scikit-learn {hardware.sklearn_version ?? "—"}
        </p>
      </div>

      {/* global actions */}
      <div className="mt-4 flex flex-wrap gap-2">
        <button
          className="btn"
          disabled={!!busy}
          onClick={() => run(() => api.discoverDatasets(), "Discover datasets")}
        >
          {busy === "Discover datasets" ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
          Discover datasets
        </button>
      </div>
      {msg && <p className="mt-2 text-[12px] text-muted">{msg}</p>}

      {/* agents */}
      <h2 className="label mt-6 mb-2">12 specialized agents</h2>
      {overview.loading && !data && (
        <div className="flex items-center gap-2 rounded-2xl border border-line bg-white p-4 text-[12.5px] text-muted shadow-card">
          <Loader2 size={14} className="animate-spin" /> loading…
        </div>
      )}
      <div className="grid gap-3 md:grid-cols-2">
        {agents.map((a: any) => {
          const meta = AGENTS.find((x) => x.id === a.id);
          const Icon = meta?.icon;
          return (
            <div key={a.id} className="rounded-2xl border border-line bg-white p-4 shadow-card">
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-2">
                  {Icon && <Icon size={16} className="text-accent" />}
                  <span className="text-[13.5px] font-medium text-paper">{a.name}</span>
                </div>
                <Badge tone={STATUS_TONE[a.status] ?? "muted"}>{a.status}</Badge>
              </div>
              <p className="mt-1 text-[11.5px] text-muted">{a.purpose}</p>

              <div className="mt-2 flex flex-wrap gap-3 text-[11.5px] text-muted">
                <span>samples: {a.training_samples}</span>
                {a.last_run && <span>last run: {a.last_run.status}</span>}
                {a.model && <span>model: {a.model.version}</span>}
              </div>

              {/* datasets */}
              {a.datasets?.length > 0 && (
                <div className="mt-2">
                  <p className="text-[10.5px] text-muted">Datasets:</p>
                  <ul className="mt-0.5 space-y-0.5 text-[11px] text-paper/80">
                    {a.datasets.map((d: any) => (
                      <li key={d.id}>
                        {d.id} — {d.status}
                        {d.has_labelled_features && <span className="text-success"> (labelled)</span>}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* actions */}
              <div className="mt-3 flex flex-wrap gap-1.5">
                {a.datasets?.[0] && (
                  <button
                    className="btn py-1 text-[11.5px]"
                    disabled={!!busy}
                    onClick={() => run(() => api.prepareDataset({ dataset_id: a.datasets[0].id }), `Prepare ${a.id}`)}
                  >
                    Prepare
                  </button>
                )}
                <button
                  className="btn py-1 text-[11.5px]"
                  disabled={!!busy || a.status === "Training"}
                  onClick={() =>
                    run(
                      () => api.startTraining(a.id, { dataset_id: a.datasets?.[0]?.id }),
                      `Train ${a.id}`
                    )
                  }
                >
                  <Play size={11} /> Train
                </button>
                <button
                  className="btn py-1 text-[11.5px]"
                  disabled={!!busy}
                  onClick={() => run(() => api.evaluateAgent(a.id), `Evaluate ${a.id}`)}
                >
                  Evaluate
                </button>
                {a.model && (
                  <>
                    <button
                      className="btn py-1 text-[11.5px]"
                      disabled={!!busy}
                      onClick={() => run(() => api.deployModel(a.model.id), `Deploy ${a.id}`)}
                    >
                      Deploy
                    </button>
                    <button
                      className="btn py-1 text-[11.5px]"
                      disabled={!!busy}
                      onClick={() => run(() => api.rollbackModel(a.model.id), `Rollback ${a.id}`)}
                    >
                      Rollback
                    </button>
                  </>
                )}
              </div>

              {a.last_run?.notes && (
                <p className="mt-2 text-[10.5px] leading-4 text-muted line-clamp-2">
                  {a.last_run.notes}
                </p>
              )}
            </div>
          );
        })}
      </div>

      {/* models */}
      <h2 className="label mt-6 mb-2">Model registry</h2>
      {data?.models?.length === 0 && (
        <div className="rounded-2xl border border-line bg-white shadow-card">
          <EmptyState compact title="No trained models registered." hint="Train an agent to create a model checkpoint." />
        </div>
      )}
      {data?.models?.length > 0 && (
        <ul className="divide-y divide-line/70 overflow-hidden rounded-2xl border border-line bg-white shadow-card">
          {data.models.map((m: any) => (
            <li key={m.id} className="flex items-center gap-3 px-4 py-2.5 text-[12.5px]">
              <CheckCircle2 size={14} className={m.status === "deployed" ? "text-success" : "text-muted"} />
              <span className="font-medium text-paper">{m.id}</span>
              <span className="text-muted">{m.agent_id}</span>
              <span className="ml-auto text-muted">{m.status}</span>
              <span className="text-muted">{m.version}</span>
            </li>
          ))}
        </ul>
      )}

      {/* runs */}
      <h2 className="label mt-6 mb-2">Training history</h2>
      {data?.runs?.length === 0 && (
        <div className="rounded-2xl border border-line bg-white shadow-card">
          <EmptyState compact title="No training runs yet." />
        </div>
      )}
      {data?.runs?.length > 0 && (
        <ul className="divide-y divide-line/70 overflow-hidden rounded-2xl border border-line bg-white shadow-card">
          {data.runs.map((r: any) => (
            <li key={r.id} className="px-4 py-2.5 text-[12px]">
              <span className="font-medium text-paper">{r.agent_id}</span>
              <span className="ml-2 text-muted">{r.status}</span>
              <span className="ml-2 text-muted">{r.started_at}</span>
              {r.notes && <p className="mt-0.5 text-[11px] text-muted line-clamp-1">{r.notes}</p>}
            </li>
          ))}
        </ul>
      )}

      <p className="mt-6 text-[11.5px] leading-5 text-muted">
        Note: agents show "Awaiting Labels" because no labelled feature tables (features.npz) are present in this
        deployment. Place a labelled feature table at the dataset path shown above to enable real training. No
        metrics are invented; all results come from actual executed training runs.
      </p>
    </div>
  );
}

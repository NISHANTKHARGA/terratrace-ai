// App shell: compact top navigation (Analyze / Map / Reports), logo, and a
// tiny backend status dot. Deliberately minimal — TerraTrace AI is a
// three-step tool, not a dashboard.

import { createContext, useContext, type ReactNode } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { Map as MapIcon, Radar, ScrollText } from "lucide-react";
import { useApi } from "../services/api";
import type { HealthResponse } from "../types";

interface HealthState {
  health: HealthResponse | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

const HealthContext = createContext<HealthState>({
  health: null,
  loading: true,
  error: null,
  refetch: () => {},
});

export function useHealth(): HealthState {
  return useContext(HealthContext);
}

function HealthProvider({ children }: { children: ReactNode }) {
  const { data, loading, error, refetch } = useApi<HealthResponse>("/api/health");
  const value: HealthState = { health: data, loading, error, refetch };
  return <HealthContext.Provider value={value}>{children}</HealthContext.Provider>;
}

const NAV = [
  { to: "/", label: "Analyze", icon: Radar, end: true },
  { to: "/map", label: "Map", icon: MapIcon },
  { to: "/reports", label: "Reports", icon: ScrollText },
];

const TITLES: Record<string, string> = {
  "/": "Select an area",
  "/map": "Global map",
  "/reports": "Reports",
};

/** Tiny status dot in the nav — technical health stays out of the way. */
function StatusDot() {
  const { health, loading, error } = useHealth();
  const state = error
    ? { cls: "bg-danger", label: "offline" }
    : loading
      ? { cls: "bg-line2", label: "…" }
      : health?.status === "ok"
        ? { cls: "bg-success", label: "ready" }
        : health
          ? { cls: "bg-amber-500", label: "partial" }
          : { cls: "bg-danger", label: "offline" };
  return (
    <span
      className="no-print flex items-center gap-1.5 text-[11px] text-muted"
      title={`API ${state.label} — database ${health?.database ?? "—"}`}
    >
      <span className={`inline-block h-2 w-2 rounded-full ${state.cls}`} />
      <span className="hidden md:inline">{state.label}</span>
    </span>
  );
}

function Shell({ children }: { children: ReactNode }) {
  const location = useLocation();
  const title = TITLES[location.pathname] ?? "TerraTrace AI";

  return (
    <div className="flex min-h-screen flex-col">
      <header className="no-print sticky top-0 z-[1200] border-b border-line bg-white/95 backdrop-blur">
        <div className="mx-auto flex h-14 w-full max-w-[1600px] items-center gap-2 px-4 sm:px-6">
          <Link to="/" className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent text-sm font-bold text-white shadow-sm">
              T
            </span>
            <span className="text-[15px] font-semibold tracking-tight text-paper">
              TerraTrace AI
            </span>
          </Link>

          <nav className="ml-4 flex items-center gap-1 sm:ml-8">
            {NAV.map(({ to, label, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) =>
                  `flex items-center gap-2 rounded-lg px-3 py-2 text-[13.5px] font-medium transition ${
                    isActive ? "bg-cyan-50 text-accent" : "text-slate-600 hover:bg-raised hover:text-paper"
                  }`
                }
              >
                <Icon size={16} strokeWidth={1.8} />
                <span className="hidden sm:inline">{label}</span>
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-3">
            <span className="hidden text-[12px] text-muted lg:inline">{title}</span>
            <StatusDot />
          </div>
        </div>
      </header>

      <main className="flex min-h-0 w-full flex-1 flex-col">{children}</main>

    </div>
  );
}

export default function Layout({ children }: { children: ReactNode }) {
  return (
    <HealthProvider>
      <Shell>{children}</Shell>
    </HealthProvider>
  );
}

export { HealthProvider };

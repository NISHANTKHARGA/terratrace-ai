// Status → tone mappings shared by every page (distinct colours per state).

import type { Tone } from "../components/ui";
import type {
  AgentStatus,
  JobStatus,
  SourceStatus,
  VerificationStatus,
} from "../types";

export function agentStatusTone(status: AgentStatus | string): Tone {
  switch (status) {
    case "operational":
      return "accent";
    case "experimental":
      return "amber";
    case "not_configured":
      return "muted";
    case "insufficient_data":
      return "steel";
    case "failed":
      return "danger";
    default:
      return "raised";
  }
}

export function jobStatusTone(status: JobStatus | string): Tone {
  switch (status) {
    case "succeeded":
      return "accent";
    case "running":
      return "steel2";
    case "queued":
      return "muted";
    case "failed":
      return "danger";
    case "cancelled":
      return "amber";
    default:
      return "raised";
  }
}

export function sourceStatusTone(status: SourceStatus | string): Tone {
  switch (status) {
    case "operational":
      return "accent";
    case "degraded":
      return "amber";
    case "requires_credentials":
      return "steel";
    case "unavailable":
      return "danger";
    default:
      return "muted";
  }
}

export function verificationTone(status: VerificationStatus | string): Tone {
  switch (status) {
    case "corroborated":
      return "accent";
    case "under_investigation":
    case "requires_verification":
      return "amber";
    case "candidate_detected":
      return "steel2";
    case "insufficient_data":
      return "steel";
    case "rejected_poor_quality":
      return "danger";
    default:
      return "raised";
  }
}

export function runStatusTone(status: string): Tone {
  switch (status) {
    case "succeeded":
    case "completed":
      return "accent";
    case "failed":
      return "danger";
    case "skipped":
    case "no_candidates":
      return "muted";
    case "timeout":
      return "amber";
    case "registered_only":
      return "steel";
    default:
      return "raised";
  }
}

export function stepStatusTone(status: string): Tone {
  switch (status) {
    case "succeeded":
      return "accent";
    case "running":
      return "steel2";
    case "pending":
      return "muted";
    case "failed":
      return "danger";
    case "skipped":
      return "amber";
    default:
      return "raised";
  }
}

export function datasetStatusTone(status: string): Tone {
  switch (status) {
    case "available":
      return "accent";
    case "registered":
      return "steel2";
    case "interface_only":
      return "steel";
    default:
      return "muted";
  }
}

export function modelStatusTone(status: string): Tone {
  switch (status) {
    case "active":
      return "accent";
    case "candidate":
      return "steel2";
    case "untrained":
      return "muted";
    case "experimental":
      return "amber";
    default:
      return "raised";
  }
}

export function severityTone(severity: string): Tone {
  switch (severity) {
    case "high":
      return "danger";
    case "moderate":
      return "amber";
    case "low":
      return "steel2";
    default:
      return "muted";
  }
}

export const TERMINAL_JOB_STATUSES: string[] = ["succeeded", "failed", "cancelled"];

export function isTerminal(status: string | null | undefined): boolean {
  return status !== null && status !== undefined && TERMINAL_JOB_STATUSES.includes(status);
}

/**
 * Analytics wire shapes (`websocket-protocol.md` §3.4, `websocket-protocol.md` §3.4).
 *
 * These are the largest payloads in the protocol. They are generated from
 * `protocol/schema.py` into the protocol module and re-exported here so
 * callers keep one import site — a field added on the Python side lands in
 * the schema and arrives here by regeneration, never by hand-copying.
 */

import type { ProfileGroup, ProfileSource } from "@/lib/ws/protocol";

export type {
  SessionListItem,
  DiskSession,
  MetricSummary,
  TrialOutcomes,
  TrialEngagement,
  ConditionOutcomes,
  RunStatus,
  ProfileSource,
  RunSummary,
  ProfileMetricInfo,
  ProfileGroup,
  AnalyticsWarning,
  AnalyticsCounts,
  AnalyticsAnimal,
  AnalyticsSummary,
  MetricSeries,
  StrategyPoint,
  TrialRecord,
  RunSeries,
  SeriesResult,
  RescanOrphan,
  RescanResult,
  RecoveredTsv,
  RecoverResult,
  AnalyticsProgress,
} from "@/lib/ws/protocol";

/** The strategy space needs exactly two metrics to have two axes (§4.3). */
export function isTwoMetricProfile(group: ProfileGroup | null): boolean {
  return group !== null && group.metrics.length === 2;
}

/** Whether a run's decoding is trustworthy, or merely current (§8.2). */
export function isProvenance(source: ProfileSource): source is "snapshot" {
  return source === "snapshot";
}

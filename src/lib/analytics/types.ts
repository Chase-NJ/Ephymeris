/**
 * Analytics wire shapes (`PROTOCOL.md#analytics`).
 *
 * These are the largest payloads in the protocol. They are generated from
 * `protocol/schema.py` into the protocol module and re-exported here so
 * callers keep one import site — a field added on the Python side lands in
 * the schema and arrives here by regeneration, never by hand-copying.
 */

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
  RescanPruned,
  RescanResult,
  RecoveredTsv,
  RecoverResult,
  TidySession,
  TidyPlan,
  AnalyticsProgress,
} from "@/lib/ws/protocol";

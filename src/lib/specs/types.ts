/**
 * Task-spec domain types. Wire shapes re-export from the generated protocol
 * mirror — never re-declared by hand — plus the handful of editor-side types
 * the wire deliberately doesn't carry.
 */

export type {
  SpecCapabilities,
  SpecCompileResult,
  SpecDiagnostic,
  SpecEntry,
  SpecGraph,
  SpecGraphEdge,
  SpecGraphNode,
  SpecOrigin,
  SpecTableSummary,
} from "@/lib/ws/protocol";

/** The parsed spec document the form binds to. Deliberately loose — the
 * compiler is the authority on what's legal, and typing it tightly here would
 * be a second schema that drifts. */
export type SpecDocument = Record<string, unknown>;

/** One field entry in the presentation overlay (task_spec.presentation.v1.json). */
export interface OverlayField {
  label: string;
  widget: string;
  group?: string;
  order?: number;
  unit?: string;
  step?: number;
  help?: string;
  advanced?: boolean;
  readOnly?: boolean;
  nullable?: boolean;
  multiple?: boolean;
  channelKind?: string;
  options?: Array<{ value: string; label: string; help?: string }>;
}

export interface OverlayGroup {
  id: string;
  label: string;
  order: number;
  help?: string;
}

export interface Overlay {
  presentation_version: number;
  groups: OverlayGroup[];
  sections: Record<string, { group: string; rows: string; gatedBy?: string }>;
  fields: Record<string, OverlayField>;
}

/** The `specs.schema` reply — everything the form needs, fetched once. */
export interface SpecSchema {
  schema: Record<string, unknown>;
  overlay: Overlay;
  strobes: Record<string, unknown>;
  channels: Record<string, unknown>;
  limits: Record<string, unknown>;
  templates: Array<{ name: string; version: number; sourceHash: string }>;
}
